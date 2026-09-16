"""
The live, interactive auction engine -- one human team competing against 9
teams driven by their real trained PPO models. Mirrors the phase flow that
already existed in the frontend (src/App.tsx) exactly, so the existing UI's
screens keep working, now driven by real data and real trained agents
instead of a hand-picked JS valuation formula:

  SET_SELECTION -> AUCTION_STAGE -> (repeat until all sets done) ->
  NOMINATION -> BOOST_ROUND -> COMPLETED

WHERE THE CLOCK LIVES. The frontend drives it, not the backend. Every AI
decision is instant (a model.predict() call), so rather than run an async
timer server-side, the frontend ticks and asks this engine for the next
raise; the engine stays pure request/response and holds no timers. That
keeps pausing, speed controls (LIVE/FAST/INSTANT) and skipping entirely
client-side.

Bidding flow for one player -- a real ascending auction, not a poll:
  1. The lot opens and one team bids. That team and the next to answer it
     form a DUEL.
  2. The clock ticks. Only the duel's two members trade raises; everyone
     else watches, exactly as in a real room.
  3. When the leader goes unanswered, the count begins: GOING ONCE ->
     TWICE -> THRICE. During the count OUTSIDERS MAY CUT IN, which resets
     the count and forms a new duel -- the late steal that makes an
     auction worth watching.
  4. The count running out is the ONLY thing that ends a lot. The human
     bidding or passing changes the price, never the outcome.

The human's controls: BID joins the duel, PASS declines this price (the
clock carries on without them), SIT OUT abandons the lot entirely, and
AUTO-BID leaves a proxy instruction that answers up to a set ceiling.

BOOST_ROUND players are auctioned at HALF their base price (matching
App.tsx's isBoost handling), and its player list is the union of the
human's up-to-5 nominations plus AI teams' own nominations (each AI team
nominates unsold players matching its biggest role gaps) -- ported from
App.tsx's handleLaunchBoostRound. Once the boost queue is exhausted, any
team still short of 20 players is force-filled from the remaining unsold
pool (or an emergency filler if that's exhausted too) -- ported from
App.tsx's autoDraftSquadFillers, guaranteeing every team finishes at
exactly 20 players.
"""

from __future__ import annotations

import random

from rl.auction_mdp import (
    PoolLookahead, build_observation, clip_willingness, next_bid, same_caliber_left,
)
from rl.squad_rules import role_deficits
from rl.team_bot import MAX_OVERSEAS, SQUAD_TARGET, TeamState, bot_willingness
from rl.data_loader import AuctionPlayer, load_player_pool, load_team_profiles
from rl.fair_price import fair_price_cr

from .model_registry import TEAM_IDS, ModelRegistry
from .sets import get_unique_sets, players_in_set

# How much a team's willingness varies on the day, as a fraction of its own
# valuation (lognormal sigma).
#
# WHY THIS EXISTS. The policy returns one fixed ceiling per team per player,
# and an ascending auction always awards the lot to the highest ceiling --
# so without noise the winner is decided before a single bid is made, and
# the SAME team wins the SAME player in every playthrough. Measured on the
# opening set, the top two ceilings differ by a median of just 3.2%, yet MI
# won Ruturaj Gaikwad 20 times out of 20.
#
# This is not a flaw in the model: it values the player sensibly. It is a
# flaw in treating a point estimate as a hard limit. Real bidders arrive
# with a range, not a number -- what they just paid for someone else, who
# is injured, nerve.
#
# 6% is CALIBRATED, not guessed. It is roughly double the measured 3.2%
# gap, which is enough for teams genuinely in contention to trade the
# player between playthroughs while the model's own judgement still shows
# through: MI, who values Gaikwad highest, wins him 29% of the time across
# 80 runs, with 8 different franchises winning overall. Pushing it to 12%
# INVERTED the ranking -- RCB started beating MI for a player MI values
# more -- which throws away exactly what the training bought.
# Set to 0.0 to restore the old deterministic behaviour.
BID_NOISE_SIGMA = 0.06

MAX_NOMINATIONS = 5
MAX_AI_NOMINATIONS_PER_TEAM = 3
EMERGENCY_FILLER_PRICE_CR = 0.20

# TeamState (rl/team_bot.py) is used directly as the runtime state here --
# not a parallel reimplementation -- so the live game's eligibility rules
# (role caps, endgame must-fill-a-need logic, budget reserve) are BY
# CONSTRUCTION identical to what the model was trained against. A previous
# generation of this file had its own separate copy of this logic, which is
# exactly the kind of train/serve mismatch that caused real bugs earlier in
# this project (training on a shuffled player order while the live game
# auctions marquee-first, for one).


class AuctionRoom:
    def __init__(self, human_team_id: str, model_registry: ModelRegistry):
        if human_team_id not in TEAM_IDS:
            raise ValueError(f"Unknown team_id: {human_team_id}")
        self.human_team_id = human_team_id
        self.model_registry = model_registry
        self._rng = random.Random()

        self.all_players: list[AuctionPlayer] = load_player_pool()
        self.all_sets: list[str] = get_unique_sets(self.all_players)
        self.completed_sets: list[str] = []

        profiles_by_id = {p["team_id"]: p for p in load_team_profiles()}
        self.teams: dict[str, TeamState] = {}
        for tid in TEAM_IDS:
            seat = TeamState(tid, profiles_by_id[tid])
            seat.is_human = tid == human_team_id
            self.teams[tid] = seat

        self.phase = "SET_SELECTION"
        self.active_set: str | None = None
        self.active_set_players: list[AuctionPlayer] = []
        self.active_player_idx = -1

        self.unsold_pool: list[AuctionPlayer] = []
        self.nominated_ids: set[str] = set()
        self.boost_queue: list[AuctionPlayer] = []

        self.current_player: AuctionPlayer | None = None
        self.current_bid = 0.0
        self.current_bidder_id: str | None = None
        # Each AI team's ceiling for the player currently under the hammer,
        # asked of the policy ONCE when the lot opens (see _open_lot).
        self.ai_ceiling: dict[str, float] = {}

        # --- head-to-head duel state (see _next_raise) ---
        # A real room is a DUEL: two teams trade raises while everyone else
        # watches, and a third only cuts in once one of them has dropped.
        # `duel` holds the (at most two) teams currently trading.
        self.duel: list[str] = []
        # The human sat this lot out -- stop asking, let the AI finish it.
        self.human_out = False
        # Proxy bid: raise for the human automatically up to this ceiling.
        self.auto_bid_limit: float | None = None

    # --- shared bidding mechanics (used by both AUCTION_STAGE and BOOST_ROUND) ---

    def _is_boost(self) -> bool:
        return self.phase == "BOOST_ROUND"

    def _effective_base_price(self, player: AuctionPlayer) -> float:
        return player.base_price_cr * 0.5 if self._is_boost() else player.base_price_cr

    def _ai_team_ids(self) -> list[str]:
        return [tid for tid in TEAM_IDS if tid != self.human_team_id]

    def _remaining_players(self) -> list[AuctionPlayer]:
        """Approximates 'players left in the whole auction' for the
        observation's scarcity features. Training used a single flat
        sequential pool; the live game auctions set-by-set, so this counts
        every player nobody has bought yet -- close enough for a feature
        that's clamped and normalised in build_observation, not a hard
        rule."""
        owned_ids = {p.player_id for t in self.teams.values() for p in t.squad}
        return [p for p in self.all_players if p.player_id not in owned_ids]

    def _open_lot(self, player: AuctionPlayer) -> None:
        """Ask every AI team, once, what this player is worth to it.

        The trained policy outputs ONE valuation per player (a multiple of
        the price model's fair price), not a bid/pass decision per
        increment -- so the ceiling is decided here, up front, and the
        ascending auction below simply plays out against those numbers.
        That is also how a real ascending auction works: bidders arrive
        with a limit and drop out when the price passes it.

        It is cheaper than the old design too -- one model call per team
        per player instead of one per team per increment.
        """
        fair = fair_price_cr(player)
        remaining = self._remaining_players()
        total = len(self.all_players)
        caliber = same_caliber_left(remaining, player)
        lookahead = PoolLookahead(remaining, {p.player_id: fair_price_cr(p) for p in remaining})
        # features(-1) = everything still to come, which is exactly what the
        # remaining pool is here.
        look = lookahead.features(-1)

        self.ai_ceiling = {}
        for team_id in self._ai_team_ids():
            seat = self.teams[team_id]
            obs = build_observation(
                seat=seat, player=player, fair=fair, caliber_left=caliber,
                players_left=len(remaining), total_players=total, lookahead=look,
                # Ask the loaded model what shape IT expects, rather than
                # assume -- this same code path is used to evaluate
                # candidate models (see reports/gate_market_health.py)
                # whose observation shape can differ from the live model's.
                include_pace_spin=self.model_registry.include_pace_spin(),
                team_variant=self.model_registry.team_variant(),
            )
            if self.model_registry.has_model(team_id):
                willing = self.model_registry.willingness_multiplier(obs) * fair
            else:
                # No trained policy on disk (fresh checkout, or mid-retrain):
                # fall back to the scripted archetype the curriculum trains
                # against, so the room is still playable rather than dead.
                willing = bot_willingness(seat, player, fair)
            # Private-value noise: this team's appetite for THIS player on
            # THIS day. Applied before the safety clip so it can never push
            # a bid past the hard cap. See BID_NOISE_SIGMA.
            if BID_NOISE_SIGMA > 0.0:
                willing *= self._rng.lognormvariate(0.0, BID_NOISE_SIGMA)
            self.ai_ceiling[team_id] = clip_willingness(seat, willing, fair)

    def _can_raise(self, team_id: str, proposed: float) -> bool:
        """Is this AI team still in for the player, at this price?"""
        if team_id == self.current_bidder_id:
            return False
        if proposed > self.ai_ceiling.get(team_id, 0.0):
            return False  # past its limit -- it has dropped out
        return self.teams[team_id].is_eligible_for(self.current_player, proposed)

    def _next_raise(self, allow_new_entrant: bool) -> list[dict]:
        """One raise from the AI, respecting the head-to-head DUEL rule.

        A real auction is not ten teams shouting at once. Two bidders trade
        raises while the rest watch; a third only cuts in once one of the
        two has dropped out -- and when it does, it almost always happens
        late, during the going-once/going-twice count. That late jump-in is
        the most dramatic moment in the room, so it is modelled explicitly:

          allow_new_entrant=False -> only the duel's other half may answer.
          allow_new_entrant=True  -> anyone still under their ceiling may
                                     cut in (the frontend passes this only
                                     while the hammer is coming down).
        """
        player = self.current_player
        proposed = next_bid(self.current_bid, self._effective_base_price(player))

        # With fewer than two teams committed there is no duel to protect
        # yet -- the opening bidder needs somebody to answer it, so the
        # room is open until a pair has formed.
        if allow_new_entrant or len(self.duel) < 2:
            candidates = [t for t in self._ai_team_ids() if self._can_raise(t, proposed)]
        else:
            # Strictly the opponent already locked in this duel.
            candidates = [t for t in self.duel if self._can_raise(t, proposed)]

        if not candidates:
            return []

        # Weighted by HEADROOM: a team whose ceiling is far above the
        # current price is keener and jumps in more often, while one
        # scraping its limit rarely does. That thins the room out as the
        # price climbs, instead of one franchise answering every time.
        weights = [max(0.01, self.ai_ceiling[t] - proposed) for t in candidates]
        team_id = self._rng.choices(candidates, weights=weights, k=1)[0]

        holder = self.current_bidder_id
        self.current_bid = proposed
        self.current_bidder_id = team_id
        # The duel is now exactly these two: the new leader and whoever it
        # just outbid. Anyone else has to wait for one of them to drop.
        self.duel = [t for t in (holder, team_id) if t is not None]
        return [{"type": "BID", "team_id": team_id, "amount": self.current_bid}]

    def ai_tick(self, allow_new_entrant: bool = False) -> list[dict]:
        """One beat of the auction clock, driven by the frontend.

        Returns a BID if someone raised, or [] meaning "nobody answered" --
        which is the frontend's cue to advance the going-once/twice/thrice
        count. It calls back with allow_new_entrant=True during that count
        so a fresh team can still steal the lot before the hammer falls.
        """
        if self.phase not in ("AUCTION_STAGE", "BOOST_ROUND") or self.current_player is None:
            return []
        # A proxy bid answers before any AI does -- it is the human's own
        # standing instruction, not a reaction to it.
        auto = self._auto_bid_raise()
        if auto:
            return auto
        return self._next_raise(allow_new_entrant)

    def _auto_bid_raise(self) -> list[dict]:
        """Raise on the human's behalf while the price is under their cap."""
        if self.auto_bid_limit is None or self.human_out:
            return []
        if self.current_bidder_id == self.human_team_id:
            return []
        human = self.teams[self.human_team_id]
        proposed = next_bid(self.current_bid, self._effective_base_price(self.current_player))
        if proposed > self.auto_bid_limit:
            return []
        if not human.is_eligible_for(self.current_player, proposed):
            return []
        holder = self.current_bidder_id
        self.current_bid = proposed
        self.current_bidder_id = human.team_id
        self.duel = [t for t in (holder, human.team_id) if t is not None]
        return [{"type": "BID", "team_id": human.team_id, "amount": self.current_bid, "auto": True}]

    def settle_lot(self) -> list[dict]:
        """The hammer falls: award the lot and move to the next player."""
        if self.phase not in ("AUCTION_STAGE", "BOOST_ROUND") or self.current_player is None:
            return []
        events = self._finalize_current_player()
        events.extend(self._advance_within_phase())
        return events

    def sit_out(self) -> list[dict]:
        """Take no further part in this lot; let the AI teams finish it."""
        self.human_out = True
        self.auto_bid_limit = None
        return [{"type": "SAT_OUT", "player_id": self.current_player.player_id}]

    def set_auto_bid(self, limit: float | None) -> list[dict]:
        """Proxy bid: keep raising for the human up to `limit`, then stop."""
        self.auto_bid_limit = limit
        if limit is not None:
            self.human_out = False
        return [{"type": "AUTO_BID_SET", "limit_cr": limit}]

    def _one_ai_raise(self) -> list[dict]:
        """One raise with the duel left OPEN to any team.

        Used where there is no established head-to-head yet: the opening
        bid on a fresh lot, and the fast-forward path. Live bidding goes
        through ai_tick(), which keeps the duel closed until the hammer
        starts coming down.
        """
        return self._next_raise(allow_new_entrant=True)

    def _resolve_ai_round(self) -> list[dict]:
        """Play the ascending ladder out against the ceilings from _open_lot.

        Every raise is emitted as its own BID event, so the frontend can
        perform the bidding war beat by beat instead of receiving a single
        final price.
        """
        events: list[dict] = []
        player = self.current_player
        base_price = self._effective_base_price(player)

        while True:
            progressed = False
            for team_id in self._ai_team_ids():
                if team_id == self.current_bidder_id:
                    continue
                team = self.teams[team_id]
                proposed = next_bid(self.current_bid, base_price)
                if proposed > self.ai_ceiling.get(team_id, 0.0):
                    continue  # past this team's limit -- it drops out
                if not team.is_eligible_for(player, proposed):
                    continue
                self.current_bid = proposed
                self.current_bidder_id = team_id
                events.append({"type": "BID", "team_id": team_id, "amount": self.current_bid})
                progressed = True
            if not progressed:
                break
        return events

    def _finalize_current_player(self) -> list[dict]:
        player = self.current_player
        if self.current_bidder_id is None:
            # Only ONCE. A player can go under the hammer twice -- unsold in
            # the main auction, nominated into the boost round, unsold
            # again -- and appending both times put him in the pool twice.
            # The endgame filler then handed him out twice, so a squad of
            # 20 contained 19 distinct players, and two different teams
            # could even end up "owning" the same man.
            if all(q.player_id != player.player_id for q in self.unsold_pool):
                self.unsold_pool.append(player)
            return [{"type": "UNSOLD", "player_id": player.player_id, "player_name": player.name}]
        winner = self.teams[self.current_bidder_id]
        winner.buy(player, self.current_bid)
        return [{
            "type": "SOLD", "player_id": player.player_id, "player_name": player.name,
            "team_id": self.current_bidder_id, "price_cr": self.current_bid,
        }]

    def _start_bidding_on(self, player: AuctionPlayer) -> list[dict]:
        self.current_player = player
        self.current_bid = 0.0
        self.current_bidder_id = None
        # Every lot starts a fresh room: no duel, the human back in, and no
        # proxy bid carried over from the player before.
        self.duel = []
        self.human_out = False
        self.auto_bid_limit = None
        self._open_lot(player)
        # NO opening bid here. The clock places it on its first tick.
        #
        # This used to return a bid immediately, which meant SOLD and the
        # NEXT player's opening bid arrived in the same response -- so the
        # room had already started bidding on the next man before the
        # auctioneer had said his name, and no client-side pause could fix
        # it. Opening the lot silently lets the frontend read the player
        # out, and the first AI_TICK then opens the bidding at base price.
        return []

    def place_human_action(self, action: str) -> list[dict]:
        """The human's move. The CLOCK, not this method, ends a lot.

        This used to settle the player the moment no AI answered, which is
        why the room only ever moved when you clicked: pass and the hammer
        fell instantly, bid and you either won on the spot or faced exactly
        one reply. Now a decision just changes the price; ai_tick() and the
        going-once/twice/thrice count decide when the lot is over.
        """
        if self.phase not in ("AUCTION_STAGE", "BOOST_ROUND"):
            return [{"type": "ERROR", "message": f"No bidding in progress (phase={self.phase})."}]
        if action not in ("BID", "PASS", "RESOLVE"):
            return [{"type": "ERROR", "message": f"Unknown action: {action}"}]

        player = self.current_player
        events: list[dict] = []

        # RESOLVE = fast-forward: run the rest of this lot to the hammer in
        # one go. Only the explicit fast-forward control does this; normal
        # play stays bid-by-bid on the clock.
        if action == "RESOLVE":
            events.extend(self._resolve_ai_round())
            events.extend(self._finalize_current_player())
            events.extend(self._advance_within_phase())
            return events

        # PASS = "not at this price". It does NOT end the lot: the clock
        # keeps running and the rival teams carry on without you. If the
        # count runs out, whoever leads wins it.
        if action == "PASS":
            return []

        human = self.teams[self.human_team_id]
        if self.current_bidder_id == self.human_team_id:
            return [{"type": "ERROR", "message": "You already hold the leading bid."}]
        proposed = next_bid(self.current_bid, self._effective_base_price(player))
        if not human.is_eligible_for(player, proposed):
            return [{"type": "ERROR", "message": "Not eligible to raise (budget, squad, or overseas limit)."}]

        holder = self.current_bidder_id
        self.current_bid = proposed
        self.current_bidder_id = human.team_id
        self.human_out = False
        # Bidding puts you IN the duel -- from here the rival answers you
        # directly and outsiders have to wait for one of you to drop.
        self.duel = [t for t in (holder, human.team_id) if t is not None]
        return [{"type": "BID", "team_id": human.team_id, "amount": self.current_bid}]

    # --- SET_SELECTION / AUCTION_STAGE ---

    def get_available_sets(self) -> list[str]:
        return [s for s in self.all_sets if s not in self.completed_sets]

    def open_set(self, set_name: str) -> list[dict]:
        if self.phase != "SET_SELECTION":
            return [{"type": "ERROR", "message": f"Cannot open a set during phase={self.phase}."}]
        if set_name not in self.get_available_sets():
            return [{"type": "ERROR", "message": f"Set not available: {set_name}"}]

        self.active_set = set_name
        self.active_set_players = players_in_set(self.all_players, set_name)
        # Shuffle the lot order INSIDE the set. The CSV lists players in a
        # fixed order, so without this the same name opened the same set
        # every single game -- Ruturaj Gaikwad was lot 1 of M1 forever.
        #
        # Only the order within the set changes; which players belong to
        # which set is real data and is left alone.
        self._rng.shuffle(self.active_set_players)
        self.active_player_idx = 0
        self.phase = "AUCTION_STAGE"
        return self._start_bidding_on(self.active_set_players[0])

    def _advance_within_phase(self) -> list[dict]:
        if self.phase == "AUCTION_STAGE":
            return self._advance_auction_stage()
        return self._advance_boost_round()

    def _advance_auction_stage(self) -> list[dict]:
        self.active_player_idx += 1
        if self.active_player_idx < len(self.active_set_players):
            return self._start_bidding_on(self.active_set_players[self.active_player_idx])

        # Set complete.
        self.completed_sets.append(self.active_set)
        self.active_set = None
        self.current_player = None
        if set(self.get_available_sets()) == set():
            self.phase = "NOMINATION"
            return [{"type": "SET_COMPLETE"}, {"type": "NOMINATION_PHASE_STARTED", "unsold_pool_size": len(self.unsold_pool)}]
        self.phase = "SET_SELECTION"
        return [{"type": "SET_COMPLETE"}]

    # --- NOMINATION / BOOST_ROUND ---

    def toggle_nomination(self, player_id: str) -> list[dict]:
        if self.phase != "NOMINATION":
            return [{"type": "ERROR", "message": f"Not in nomination phase (phase={self.phase})."}]
        if not any(p.player_id == player_id for p in self.unsold_pool):
            return [{"type": "ERROR", "message": "Player is not in the unsold pool."}]

        if player_id in self.nominated_ids:
            self.nominated_ids.remove(player_id)
        else:
            if len(self.nominated_ids) >= MAX_NOMINATIONS:
                return [{"type": "ERROR", "message": f"You can only nominate a maximum of {MAX_NOMINATIONS} players."}]
            self.nominated_ids.add(player_id)
        return [{"type": "NOMINATION_UPDATED", "nominated_ids": sorted(self.nominated_ids)}]

    # Role targets an AI team nominates toward, ported from App.tsx's
    # handleLaunchBoostRound (which distinguished Fast/Spin bowler at <3/<2;
    # our data doesn't split bowler by pace/spin, so those two merge to <5).
    _ROLE_NOMINATION_TARGETS = {"Wicketkeeper": 1, "Batter": 3, "All-rounder": 2, "Bowler": 5}

    def _ai_nominations(self) -> list[AuctionPlayer]:
        """Each AI team nominates unsold players matching its biggest role
        gaps, ported from App.tsx's handleLaunchBoostRound."""
        already_picked: set[str] = set()
        nominations: list[AuctionPlayer] = []

        for team_id in self._ai_team_ids():
            team = self.teams[team_id]
            if team.slots_remaining <= 0:
                continue
            needed_roles = [
                r for r, target in self._ROLE_NOMINATION_TARGETS.items()
                if team.role_count(r) < target
            ]
            matching = [
                p for p in self.unsold_pool
                if (not needed_roles or p.role in needed_roles)
                and p.player_id not in self.nominated_ids
                and p.player_id not in already_picked
            ]
            chosen = matching[:MAX_AI_NOMINATIONS_PER_TEAM]
            nominations.extend(chosen)
            already_picked.update(p.player_id for p in chosen)
        return nominations

    def launch_boost_round(self) -> list[dict]:
        if self.phase != "NOMINATION":
            return [{"type": "ERROR", "message": f"Not in nomination phase (phase={self.phase})."}]

        human_noms = [p for p in self.unsold_pool if p.player_id in self.nominated_ids]
        ai_noms = self._ai_nominations()
        full_pool = human_noms + ai_noms

        if not full_pool:
            full_pool = self.unsold_pool[:8]

        # Dedupe: the same player can be nominated by the human AND by an AI
        # team, which would otherwise put him under the hammer twice.
        seen: set[str] = set()
        unique_pool = []
        for p in full_pool:
            if p.player_id not in seen:
                seen.add(p.player_id)
                unique_pool.append(p)

        # Shuffle for the same reason the sets are shuffled: concatenating
        # the lists left the human's own nominations always going first.
        self._rng.shuffle(unique_pool)
        self.boost_queue = unique_pool
        self.phase = "BOOST_ROUND"
        self.active_player_idx = 0
        if not self.boost_queue:
            return self._finish_boost_round()
        return self._start_bidding_on(self.boost_queue[0])

    def _advance_boost_round(self) -> list[dict]:
        self.active_player_idx += 1
        if self.active_player_idx < len(self.boost_queue):
            return self._start_bidding_on(self.boost_queue[self.active_player_idx])
        return self._finish_boost_round()

    @staticmethod
    def _most_needed_role(team: TeamState) -> str:
        """The role this squad most needs to reach a legal XI."""
        d = role_deficits(team.squad)
        if d["Wicketkeeper"] > 0:
            return "Wicketkeeper"
        if d["SpecialistBowler"] > 0:
            return "Bowler"
        if d["BowlingOption"] > 0:
            return "All-rounder"
        if d["Batter"] > 0:
            return "Batter"
        return "Batter"

    @staticmethod
    def _best_filler_index(team: TeamState, pool: list[AuctionPlayer]) -> int | None:
        """Pick the leftover player who best repairs this squad.

        BUG FIX: this used to take the FIRST eligible name in the list,
        ignoring what the team was short of. A team that reached 20 players
        without ever buying a wicketkeeper got handed whatever came first --
        usually another batter -- and finished unable to field a legal XI at
        all. Seed 7 produced exactly that: RCB, 20 players, zero keepers.
        """
        d = role_deficits(team.squad)
        best_i, best_key = None, None
        for i, p in enumerate(pool):
            if p.is_overseas and team.overseas_count >= MAX_OVERSEAS:
                continue
            need = 0
            if d["Wicketkeeper"] > 0 and p.role == "Wicketkeeper":
                need = 4
            elif d["SpecialistBowler"] > 0 and p.role == "Bowler":
                need = 3
            elif d["BowlingOption"] > 0 and p.role in ("Bowler", "All-rounder"):
                need = 2
            elif d["Batter"] > 0 and p.role == "Batter":
                need = 1
            key = (need, p.value_score)
            if best_key is None or key > best_key:
                best_i, best_key = i, key
        return best_i

    def _finish_boost_round(self) -> list[dict]:
        """Guarantees every team finishes at exactly 20 players -- ported
        from App.tsx's autoDraftSquadFillers."""
        self.current_player = None
        remaining_unsold = []
        seen_ids: set[str] = set()
        for p in self.unsold_pool:
            if p.player_id in seen_ids or self.teams_have(p.player_id):
                continue
            seen_ids.add(p.player_id)
            remaining_unsold.append(p)
        events = []

        for team_id in TEAM_IDS:
            team = self.teams[team_id]
            while team.slots_remaining > 0:
                idx = self._best_filler_index(team, remaining_unsold)
                if idx is not None:
                    player = remaining_unsold.pop(idx)
                    price = min(player.base_price_cr, team.budget)
                    team.buy(player, price)
                    events.append({"type": "AUTO_FILLED", "team_id": team_id, "player_name": player.name, "price_cr": price})
                else:
                    # The academy prospect plays wherever the squad is
                    # short, not always as a batter.
                    filler_role = self._most_needed_role(team)
                    filler = AuctionPlayer(
                        player_id=f"emergency-{team_id}-{len(team.squad)}",
                        name=f"{team_id.upper()} Academy Prospect",
                        role=filler_role, country="India", is_overseas=False, capped=False,
                        base_price_cr=EMERGENCY_FILLER_PRICE_CR, value_score=20.0,
                        value_score_is_real=False, set_name="",
                    )
                    price = min(EMERGENCY_FILLER_PRICE_CR, team.budget)
                    team.buy(filler, price)
                    events.append({"type": "EMERGENCY_FILLER", "team_id": team_id, "player_name": filler.name, "price_cr": price})

        self.phase = "COMPLETED"
        events.append({"type": "AUCTION_COMPLETE"})
        return events

    @staticmethod
    def _price_paid(team: TeamState, player_id: str) -> float:
        """TeamState records purchases as a (player, price) list rather than
        the player_id->price dict the old TeamSeat exposed. Squads cap at 20,
        so the scan is cheaper than maintaining a parallel index."""
        for bought_player, price in team.bought:
            if bought_player.player_id == player_id:
                return price
        return 0.0

    def teams_have(self, player_id: str) -> bool:
        return any(
            any(bp.player_id == player_id for bp, _ in t.bought)
            for t in self.teams.values()
        )

    # --- state for the frontend ---

    @staticmethod
    def _player_summary(player: AuctionPlayer, base_price_override: float | None = None) -> dict:
        return {
            "player_id": player.player_id,
            "name": player.name,
            "role": player.role,
            "country": player.country,
            "is_overseas": player.is_overseas,
            "capped": player.capped,
            "value_score": player.value_score,
            "value_score_is_real": player.value_score_is_real,
            "bowler_subtype": player.bowler_subtype,
            # What the trained XGBoost price model thinks this player is
            # worth. It already drives every AI team's ceiling, so showing it
            # tells the human what the market reckons BEFORE they bid --
            # which is the whole point of having a price model.
            "fair_price_cr": round(fair_price_cr(player), 2),
            "base_price_cr": base_price_override if base_price_override is not None else player.base_price_cr,
        }

    def get_state_snapshot(self) -> dict:
        player = self.current_player
        return {
            "phase": self.phase,
            "human_team_id": self.human_team_id,
            "available_sets": self.get_available_sets() if self.phase == "SET_SELECTION" else [],
            "active_set": self.active_set,
            "current_player": None if player is None else self._player_summary(
                player, self._effective_base_price(player) if self.phase in ("AUCTION_STAGE", "BOOST_ROUND") else None
            ),
            "current_bid": self.current_bid,
            "current_bidder_id": self.current_bidder_id,
            # The two teams currently trading raises -- the UI highlights
            # them and greys the rest, so it is visible that the room is a
            # duel and not a free-for-all.
            "duel": list(self.duel),
            "human_out": self.human_out,
            "auto_bid_limit": self.auto_bid_limit,
            "unsold_pool": [self._player_summary(p) for p in self.unsold_pool] if self.phase == "NOMINATION" else [],
            "nominated_ids": sorted(self.nominated_ids),
            "teams": {
                tid: {
                    "budget": t.budget,
                    "overseas_count": t.overseas_count,
                    "squad": [
                        {**self._player_summary(p), "buy_price_cr": self._price_paid(t, p.player_id)}
                        for p in t.squad
                    ],
                }
                for tid, t in self.teams.items()
            },
        }
