"""
The auction MDP, rebuilt around a VALUATION action space.

WHY THE REWRITE. The previous design asked PPO for a BID/PASS decision at
every bid increment (~700 decisions per episode), which is a brutal
credit-assignment problem. To make it learnable, five hand-designed shaped
reward terms were bolted on (identity match, pace/spin match, budget
pacing, overpay penalty, purchase quality). Every one was individually
verified and every fix to one broke another: symmetric overpay fixed
cap-pinning and created pass-on-everything; completeness weighting fixed
first-purchase and broke wrong-role; the quality boost fixed elite-steals
and broke squad completion. That is the signature of an over-constrained
design, not five unlucky bugs -- each term was a partial proxy for the same
underlying thing, so they fought.

WHAT REPLACES IT.

  Action: one number per player -- a multiplier m in [0, 3] on the ML
  model's predicted fair price. Willingness = m * fair_price_cr(player).
  The price model supplies the units, so the policy never has to learn the
  absolute price scale, only "how much more or less than market is this
  player worth to ME".

  Reward: the ENTIRE reward is
      per purchase : xi_strength(after) - xi_strength(before)
      per purchase : + SLOT_POTENTIAL (see that constant)
                     -NO_LEGAL_XI_PENALTY if no legal XI
  No weights, no scale constants, no clamps, no normalisers. Because the
  per-purchase term telescopes (an empty squad has xi_strength 0), the
  undiscounted episode return is exactly
      xi_strength(final squad) - penalties
  so the dense signal and the terminal objective cannot disagree.

  Overpaying is self-penalising and needs no term: spend 40 Cr on one
  player and you cannot afford a legal XI, which the terminal penalty
  charges you for. Winning cheap is strictly good, because nothing can
  punish it.

  Team identity is an OBSERVATION feature (via FiLM), not a reward term.
  The policy learns each franchise's valuation style because it is
  conditioned on that franchise, not because a term pays it to comply.

THE TWO RULES, enforced by construction here:
  1. No reward term may see price paid. (There is only one reward term and
     it reads xi_strength, which cannot see price.)
  2. No term gets added to fix behaviour without re-running the full gate
     panel.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from stable_baselines3 import PPO

from .data_loader import AuctionPlayer, load_player_pool, load_team_history_features, load_team_profiles
from .fair_price import fair_price_cr
from .squad_rules import (
    MIN_BATTERS,
    MIN_BOWLING_OPTIONS,
    MIN_SPECIALIST_BOWLERS,
    MIN_WICKETKEEPERS,
    has_legal_xi,
    is_bowling_option,
    min_players_still_needed,
    role_deficits,
    xi_strength,
)
from .team_bot import (
    MAX_OVERSEAS,
    MAX_PRICE_TO_FAIR_MULTIPLIER,
    ROLES,
    SQUAD_TARGET,
    TeamState,
    aggression_factor,
    bot_willingness,
)

RL_DIR = Path(__file__).resolve().parent
SNAPSHOT_POOL_DIR = RL_DIR / "self_play_snapshots"

BUDGET_CR = 125.0
MAX_VALUATION_MULTIPLIER = 3.0

# Accelerated ("boost") round: re-auction everyone unsold on the main pass at
# half base price, as the live game's BOOST_ROUND does. DISABLED -- it was
# tried, measured, and removed.
#
# Why it was tried: without it a player gets one pass and is gone, so elite
# players deep in the pool (B Sai Sudharsan 80, Harry Brook 72, Tim David
# 72) went entirely unsold. It did fix that narrow problem -- those players
# started selling, and full squads for the incumbent model rose 93.6% ->
# 97.6%.
#
# Why it was removed: it makes DEFERRING cheap, and that generalises
# catastrophically to self-play. An agent learns it can skip the main pass
# and collect half-price leftovers. That works against scripted bots (which
# keep bidding regardless, so the diagnostic showed healthy 18.4-20.0
# squads) and collapses when all ten seats are the same policy -- every
# team defers, nobody bids in the second pass, and all ten finish short. In
# the all-AI gate, 37 of 37 incomplete squads could afford more players and
# simply did not bid. Measured across two independent training runs, one on
# the buggy reward and one on the fixed reward, so it is not run variance:
#     with boost round    -> mean squad 16.70, mean return 31.12
#     without boost round -> mean squad 19.92, mean return 48.02
# Same family as the v3->v4 failure: behaviour that is rational against the
# training opponent distribution and self-defeating against copies of
# itself.
#
# If unsold-player recovery is wanted later, re-enable at FULL base price
# (BOOST_BASE_PRICE_MULTIPLIER = 1.0), which removes the reward for waiting.
# Do not re-enable at half price without re-running the full gate panel.
BOOST_ROUND_ENABLED = False
BOOST_BASE_PRICE_MULTIPLIER = 0.5

# The only numbers in the reward besides xi_strength.
#
# SLOT_POTENTIAL is paid as POTENTIAL-BASED SHAPING (Ng, Harada &
# Russell 1999), not as a terminal penalty: Phi(s) = SLOT_POTENTIAL *
# len(squad), so every purchase pays it at the moment it happens and the
# terminal "-N per missing slot" disappears. Total return shifts by a
# constant, so the OPTIMAL POLICY IS PROVABLY UNCHANGED -- only WHEN the
# signal arrives changes, from hundreds of decisions later to immediately.
#
# Why it was needed: a forced-continue test showed the policy stopping at
# 15-19 players while holding spare budget, and forcing it to buy scored
# STRICTLY BETTER every time it managed an extra purchase (+6.87 for one
# more, +18.97 for filling up; one seed went -12.38 -> +48.83). So the
# reward already paid for those slots and the policy simply wasn't
# capturing it -- a credit-assignment problem, since buying a filler paid
# ~0 immediately and the slot value only landed at the end of the episode.
#
# NO_LEGAL_XI_PENALTY stays TERMINAL: it is not a per-slot count, so it
# does not decompose into a per-purchase potential the same way.
# MAGNITUDE: 2.0, not the 6.0 this started at, and the ratio is the whole
# argument. Completion is worth SLOT_POTENTIAL * 20 in total; squad quality
# tops out around 70 xi_strength. At 6.0 completion is worth 120 against
# 70 -- it dominates 1.7:1, so a guaranteed +6 for ANY body beats waiting
# for a player who might add two XI points. That is precisely what the gate
# measured: full squads leapt to 246/250, but the median purchase index
# collapsed to 100 (a race to buy anything, early) and legal XI fell to
# 204/250 because the race grabs whoever is cheapest rather than whoever
# completes the role requirements.
#
# DISABLED (SLOT_POTENTIAL = 0.0). Tried at three magnitudes, measured at
# each, and abandoned -- the shipped model is trained with the missing-slot
# penalty TERMINAL (see _terminal_reward), not shaped per purchase.
#
# MEASURED, all three: 6.0 (120 vs 70) -> 246/250 full squads but median
# purchase index collapsed to 100. 2.0 (40 vs 70) -> ZERO full squads,
# teams stopping at 14.8 players on 38 Cr of unspent purse. Note that is a
# cliff, not a slope: a dial does not go 246 -> 0 with nothing between, so
# this constant has a threshold in it rather than behaving linearly.
#
# 3.5 is the exact balance point (3.5 * 20 = 70 against ~70 of quality) and
# it did NOT resolve the tradeoff: 21/250 full squads, index 282, XI 55.1.
# Completion across the three runs goes 0 -> 21 -> 246, i.e. flat from 2.0
# to 3.5 then near-vertical somewhere before 6.0. That is a THRESHOLD, not
# a dial: there is no setting that buys squad completion without buying the
# race-to-buy-early along with it, so bracketing further is wasted runs.
#
# Set to 0.0 so the per-purchase term vanishes and the terminal penalty in
# _terminal_reward is the only slot signal -- which is exactly how the
# shipped model was trained (backed up at
# rl/baseline/ppo_auction_mdp_v5_BASELINE.zip). Any retrain from here
# reproduces the shipped behaviour rather than silently training something
# else.
#
# Worth recording WHY this needed tuning at all: Ng-Harada-Russell
# guarantees the OPTIMAL policy is unchanged by potential shaping, and that
# still holds. What it does not guarantee is what a LEARNED policy
# converges to under function approximation -- the immediate signal is what
# PPO actually optimises against, and 120 of immediate certainty drowns 70
# of deferred judgement.
SLOT_POTENTIAL = 0.0
# Charged terminally, per empty squad slot.
MISSING_SLOT_PENALTY = 6.0
NO_LEGAL_XI_PENALTY = 20.0

# Observation normalisers (plain scale factors, not tuned weights).
_FAIR_PRICE_SCALE = 25.0
_ROLE_COUNT_SCALE = 5.0
_CALIBER_SCALE = 30.0

# "Same caliber" = same role, value_score within this band.
CALIBER_BAND = 10.0

OBS_DIM = 45  # 21 situational + 16 pool-lookahead + 8 team -- the LIVE model's shape
# Set by include_pace_spin=True: two extra situational features (is_pace,
# is_spin). Opt-in, not the default -- the live model on disk was trained
# on the 45-dim shape, and build_observation is shared code: the live game
# (game/auction_room.py) and every trained model must keep agreeing on
# which shape they mean, or a live auction hard-crashes on every bid.
PACE_SPIN_EXTRA_DIMS = 2


def obs_dim(include_pace_spin: bool = False) -> int:
    return OBS_DIM + (PACE_SPIN_EXTRA_DIMS if include_pace_spin else 0)


# The team-identity block's CONTENT, not its size (see team_variant below).
# "baseline" (default) is the 8 features the live model was trained on.
# "star_spend" swaps in 4 real historical features from
# data/team_history_features.json, replacing the 4 weakest of the current
# 8 by a measured separation test (coefficient of variation across the 10
# real team profiles -- how much a feature actually DIFFERS between
# franchises, not a guess):
#
#   evicted (weakest, or unactionable in THIS isolated run):
#     aggression_factor        cv=11.7%  -- weakest of all 8
#     pace_spin Pace/Spin      cv=20.9/35.7%  -- these pair with the
#       PLAYER-side is_pace/is_spin features added for team_variant
#       "pace_spin" (a SEPARATE, isolated experiment -- see
#       include_pace_spin). Without that player-side signal, exactly as
#       documented above, these two team features have nothing to match
#       against, so evicting them here costs nothing this run trains for.
#     role_pct Bowler          cv=26.5%  -- weakest of the four
#       role_spend_distribution_pct fields
#
#   added (from data/team_history_features.json, real historical spend):
#     star_spend_bowler_pct       cv=26.2%
#     star_spend_allrounder_pct   cv=23.5%
#     star_spend_batter_pct       cv=20.2%
#     star_top_price_cr           cv=18.1%
#
# Kept at exactly 8 either way -- N_TEAM_FEATURES in film_policy.py and the
# FiLM slice stay untouched, so only the CONTENT of the team block changes,
# never OBS_DIM. This is also why team_variant CANNOT be inferred from a
# model's observation_space.shape the way include_pace_spin can: both
# variants are 45-dim. Callers pass the variant explicitly (see
# game/model_registry.py's tag-based ModelRegistry).
TeamVariant = str  # "baseline" | "star_spend"

_team_history_cache: dict[str, dict] | None = None


def _team_history(team_id: str) -> dict:
    global _team_history_cache
    if _team_history_cache is None:
        _team_history_cache = load_team_history_features()
    return _team_history_cache.get(team_id, {})

_SNAPSHOT_CACHE: dict[str, PPO] = {}


# --------------------------------------------------------------------------
# pool ordering
# --------------------------------------------------------------------------

def players_in_auction_order(pool: list[AuctionPlayer], rng: random.Random) -> list[AuctionPlayer]:
    """Marquee sets first (as the real auction runs them), then every other
    set in a per-episode shuffled order, players shuffled within each set.
    Ordering varies per episode so the policy can't memorise a sequence."""
    by_set: dict[str, list[AuctionPlayer]] = {}
    for p in pool:
        by_set.setdefault(p.set_name, []).append(p)

    marquee = sorted(s for s in by_set if s.upper().startswith("M"))
    others = sorted(s for s in by_set if not s.upper().startswith("M"))
    rng.shuffle(others)

    ordered: list[AuctionPlayer] = []
    for set_name in marquee + others:
        group = list(by_set[set_name])
        rng.shuffle(group)
        ordered.extend(group)
    return ordered


ELITE_VALUE_SCORE = 60.0
_LOOKAHEAD_COUNT_SCALE = 50.0
_LOOKAHEAD_ELITE_SCALE = 15.0
_LOOKAHEAD_DISTANCE_SCALE = 200.0
LOOKAHEAD_FEATURES_PER_ROLE = 4
N_LOOKAHEAD_FEATURES = LOOKAHEAD_FEATURES_PER_ROLE * len(ROLES)


class PoolLookahead:
    """What is still COMING, per role -- the auction list a real franchise
    walks in holding.

    WHY THIS EXISTS: without it the policy can only see the player in front
    of it, its own squad, and same_caliber_left. It has no way to know that
    three better keepers are coming in a later set, so taking a decent
    player now always beats an unknown future, and the policy front-loads:
    median purchase landed at index 152 of 620, squads filled before
    three-quarters of the pool had been seen, and genuinely elite players
    deep in the pool (Vaibhav Suryavanshi, Ashutosh Sharma, Priyansh Arya)
    had almost no eligible bidders left and went for base price. That is
    not the policy misbehaving -- it is the policy being blind to the thing
    teams actually plan around.

    Per role: how many are left, how many GOOD ones are left, what they
    cost on average, and how far ahead the next good one is. Precomputed
    once per episode as suffix aggregates in a single reverse pass, because
    computing it per bid would be O(n^2) over a 620-player pool.
    """

    def __init__(self, pool: list[AuctionPlayer], fair_by_id: dict[str, float]):
        n = len(pool)
        far = _LOOKAHEAD_DISTANCE_SCALE
        self._count = {r: [0] * (n + 1) for r in ROLES}
        self._elite = {r: [0] * (n + 1) for r in ROLES}
        self._fair_sum = {r: [0.0] * (n + 1) for r in ROLES}
        self._next_elite = {r: [far] * (n + 1) for r in ROLES}

        for i in range(n - 1, -1, -1):
            p = pool[i]
            fair = fair_by_id[p.player_id]
            is_elite = p.value_score >= ELITE_VALUE_SCORE
            for r in ROLES:
                match = p.role == r
                self._count[r][i] = self._count[r][i + 1] + (1 if match else 0)
                self._elite[r][i] = self._elite[r][i + 1] + (1 if match and is_elite else 0)
                self._fair_sum[r][i] = self._fair_sum[r][i + 1] + (fair if match else 0.0)
                if match and is_elite:
                    self._next_elite[r][i] = 0.0
                else:
                    self._next_elite[r][i] = min(far, self._next_elite[r][i + 1] + 1.0)

    def features(self, idx: int) -> list[float]:
        """Aggregates over everyone STILL TO COME (strictly after idx)."""
        j = min(idx + 1, len(self._count[ROLES[0]]) - 1)
        out: list[float] = []
        for r in ROLES:
            count = self._count[r][j]
            elite = self._elite[r][j]
            mean_fair = (self._fair_sum[r][j] / count) if count else 0.0
            out.append(min(2.0, count / _LOOKAHEAD_COUNT_SCALE))
            out.append(min(2.0, elite / _LOOKAHEAD_ELITE_SCALE))
            out.append(min(2.0, mean_fair / _FAIR_PRICE_SCALE))
            out.append(self._next_elite[r][j] / _LOOKAHEAD_DISTANCE_SCALE)
        return out


def same_caliber_left(remaining: list[AuctionPlayer], player: AuctionPlayer) -> int:
    """How many OTHER players still to come are the same role AND within
    CALIBER_BAND value_score of this one -- i.e. "is this my only shot at
    this kind of player, or is an equivalent coming later?". Scarcity the
    policy cannot otherwise observe."""
    return sum(
        1 for p in remaining
        if p is not player
        and p.role == player.role
        and abs(p.value_score - player.value_score) <= CALIBER_BAND
    )


def next_bid_increment(current: float) -> float:
    if current < 2.0:
        return 0.20
    if current < 5.0:
        return 0.50
    return 1.0


def next_bid(current_bid: float, base_price_cr: float) -> float:
    """What the next raise costs in an ASCENDING auction. The MDP itself
    resolves sealed-bid (one valuation per player), but the live game plays
    the bidding out increment by increment so a human can raise a paddle --
    so the ladder lives here, next to the increments it uses, rather than
    being reimplemented in game/ and in the frontend where the three copies
    would drift apart."""
    if current_bid <= 0:
        return base_price_cr
    return round(current_bid + next_bid_increment(current_bid), 2)


# --------------------------------------------------------------------------
# observation
# --------------------------------------------------------------------------

def build_observation(
    seat: TeamState,
    player: AuctionPlayer,
    fair: float,
    caliber_left: int,
    players_left: int,
    total_players: int,
    lookahead: list[float],
    include_pace_spin: bool = False,
    team_variant: TeamVariant = "baseline",
) -> np.ndarray:
    """Situational features first, team-identity block EXACTLY last 8 --
    film_policy.FiLMFeaturesExtractor slices off the tail, so the team block
    must stay at the end (see its LAYOUT CONTRACT note)."""
    deficits = role_deficits(seat.squad)
    profile = seat.profile
    role_pct = profile.get("role_spend_distribution_pct", {})
    pace_spin_pct = profile.get("pace_spin_spend_pct", {})

    situational = [
        player.value_score / 100.0,
        *[1.0 if player.role == r else 0.0 for r in ROLES],
    ]

    if include_pace_spin:
        # Does this player bowl PACE or SPIN? Opt-in (see include_pace_spin
        # above). The team block has carried each franchise's historical
        # pace/spin spend split since the v4 data work, but the policy was
        # never told which kind of bowler it was looking at -- those two
        # team features had nothing to match against. Verified: flipping a
        # bowler's subtype changed 0 of the 45 baseline dimensions.
        #
        # Only players who actually bowl are labelled -- the source CSV
        # records a bowling style for many batters who send down a few
        # part-time overs, so keying off bowler_subtype alone would call
        # Virat Kohli a pace bowler.
        #
        # POSITION MATTERS: this sits here, right after the role one-hot
        # and before is_overseas, because that is where it sat during the
        # actual training run that produced ppo_auction_mdp_v5_pace_spin.zip.
        # Moving it (e.g. to the end, after lookahead) keeps the dimension
        # count at 47 but feeds that trained model's weights a different
        # feature at each index -- silently wrong, not a crash.
        situational += [
            1.0 if (player.bowler_subtype == "Pace" and is_bowling_option(player)) else 0.0,
            1.0 if (player.bowler_subtype == "Spin" and is_bowling_option(player)) else 0.0,
        ]

    situational += [
        1.0 if player.is_overseas else 0.0,
        min(2.0, fair / _FAIR_PRICE_SCALE),
        seat.budget / BUDGET_CR,
        len(seat.squad) / SQUAD_TARGET,
        *[min(2.0, seat.role_count(r) / _ROLE_COUNT_SCALE) for r in ROLES],
        seat.overseas_count / MAX_OVERSEAS,
        deficits["Wicketkeeper"] / MIN_WICKETKEEPERS,
        deficits["Batter"] / MIN_BATTERS,
        deficits["SpecialistBowler"] / MIN_SPECIALIST_BOWLERS,
        deficits["BowlingOption"] / MIN_BOWLING_OPTIONS,
        min_players_still_needed(seat.squad) / SQUAD_TARGET,
        min(2.0, caliber_left / _CALIBER_SCALE),
        players_left / max(1, total_players),
        # What is still coming, per role -- see PoolLookahead. Appended at
        # the END of the situational block so the team block stays last, as
        # film_policy.FiLMFeaturesExtractor's layout contract requires.
        *lookahead,
    ]

    if team_variant == "star_spend":
        hist = _team_history(seat.team_id)
        team = [
            role_pct.get("All-Rounder", 25.0) / 100.0,
            role_pct.get("Batter", 25.0) / 100.0,
            role_pct.get("Wicketkeeper", 25.0) / 100.0,
            (profile.get("marquee_affinity_pct") or 20.0) / 100.0,
            hist.get("star_spend_bowler_pct", 25.0) / 100.0,
            hist.get("star_spend_allrounder_pct", 25.0) / 100.0,
            hist.get("star_spend_batter_pct", 25.0) / 100.0,
            min(2.0, hist.get("star_top_price_cr", 10.0) / _FAIR_PRICE_SCALE),
        ]
    else:
        team = [
            aggression_factor(profile),
            role_pct.get("All-Rounder", 25.0) / 100.0,
            role_pct.get("Batter", 25.0) / 100.0,
            role_pct.get("Bowler", 25.0) / 100.0,
            role_pct.get("Wicketkeeper", 25.0) / 100.0,
            pace_spin_pct.get("Pace", 50.0) / 100.0,
            pace_spin_pct.get("Spin", 50.0) / 100.0,
            (profile.get("marquee_affinity_pct") or 20.0) / 100.0,
        ]

    obs = np.array(situational + team, dtype=np.float32)
    return np.nan_to_num(obs, nan=0.0, posinf=3.0, neginf=0.0)


# --------------------------------------------------------------------------
# auction engine
# --------------------------------------------------------------------------

def clip_willingness(seat: TeamState, willingness: float, fair: float) -> float:
    """Every seat's submitted number passes through here, so no bidder --
    agent, bot or snapshot -- can ever submit something it cannot pay or
    that breaches the hard cap. This is why the resolved price is always
    affordable and eligibility never has to be rechecked afterwards."""
    return float(min(willingness, seat.max_affordable(), fair * MAX_PRICE_TO_FAIR_MULTIPLIER))


def effective_base_price(player: AuctionPlayer, is_boost_round: bool) -> float:
    """Base price for this pass. Kept as a function so the main pass and the
    boost round can never disagree between the training env and the
    evaluation harness -- an earlier hand-rolled re-simulation diverged from
    the real engine and produced squads it never generated."""
    return player.base_price_cr * (BOOST_BASE_PRICE_MULTIPLIER if is_boost_round else 1.0)


def resolve_player(
    player: AuctionPlayer,
    fair: float,
    willingness_by_seat: dict[str, float],
    seats: dict[str, TeamState],
    rng: random.Random,
    base_price: float | None = None,
) -> tuple[TeamState | None, float]:
    """Sealed-bid, second-price with an increment: the highest valuation
    wins, but pays only what it took to beat the runner-up. That mirrors how
    a real ascending auction actually clears, without simulating every
    increment -- which is the whole point of the redesign."""
    base = player.base_price_cr if base_price is None else base_price
    live = {
        tid: w for tid, w in willingness_by_seat.items()
        if w >= base and seats[tid].is_eligible_for(player, base)
    }
    if not live:
        return None, 0.0

    top = max(live.values())
    winners = [tid for tid, w in live.items() if w == top]
    winner_id = rng.choice(winners) if len(winners) > 1 else winners[0]

    others = [w for tid, w in live.items() if tid != winner_id]
    second = max(others) if others else 0.0

    price = max(base, min(top, second + next_bid_increment(second)))
    price = min(price, fair * MAX_PRICE_TO_FAIR_MULTIPLIER, seats[winner_id].max_affordable())
    # Round DOWN to the paise, not to nearest: rounding after the clamp can
    # push the price back above max_affordable (e.g. 0.295 -> 0.30) and take
    # the winner's budget fractionally negative, which then shows up as a
    # phantom "-0.00 purse left" and quietly breaks the slots-remaining
    # reserve the eligibility rule depends on.
    price = math.floor(price * 100.0) / 100.0
    return seats[winner_id], max(0.0, price)


def _load_snapshot_pool() -> list[PPO]:
    if not SNAPSHOT_POOL_DIR.exists():
        return []
    models = []
    for path in sorted(SNAPSHOT_POOL_DIR.glob("*.zip")):
        key = str(path)
        if key not in _SNAPSHOT_CACHE:
            _SNAPSHOT_CACHE[key] = PPO.load(path, device="cpu")
        models.append(_SNAPSHOT_CACHE[key])
    return models


def multiplier_from_model(model: PPO, obs: np.ndarray, deterministic: bool = True) -> float:
    action, _ = model.predict(obs, deterministic=deterministic)
    return float(np.clip(np.asarray(action).reshape(-1)[0], 0.0, MAX_VALUATION_MULTIPLIER))


# --------------------------------------------------------------------------
# the environment
# --------------------------------------------------------------------------

class AuctionMDPEnv(gym.Env):
    """One full auction. The learner holds one franchise seat; the other
    nine are scripted bots or frozen self-play snapshots."""

    metadata = {"render_modes": []}

    def __init__(
        self,
        agent_team_id: str | None = None,
        opponent_trained_fraction: float = 0.0,
        seed: int | None = None,
        include_pace_spin: bool = False,
        team_variant: TeamVariant = "baseline",
    ):
        super().__init__()
        self.include_pace_spin = include_pace_spin
        self.team_variant = team_variant
        self.action_space = spaces.Box(
            low=0.0, high=MAX_VALUATION_MULTIPLIER, shape=(1,), dtype=np.float32
        )
        self.observation_space = spaces.Box(
            low=-1.0, high=5.0, shape=(obs_dim(include_pace_spin),), dtype=np.float32
        )

        self._pool_source = load_player_pool()
        self._profiles = {p["team_id"]: p for p in load_team_profiles()}
        self._team_ids = list(self._profiles)
        self._fixed_agent_team_id = agent_team_id
        self.opponent_trained_fraction = opponent_trained_fraction
        self._rng = random.Random(seed)

        self.agent: TeamState | None = None
        self._done = True

    # -- setup ------------------------------------------------------------

    def reset(self, *, seed: int | None = None, options=None):
        super().reset(seed=seed)
        if seed is not None:
            self._rng = random.Random(seed)

        agent_id = self._fixed_agent_team_id or self._rng.choice(self._team_ids)
        self.seats = {
            tid: TeamState(tid, self._profiles[tid], self._rng) for tid in self._team_ids
        }
        self.agent = self.seats[agent_id]

        snapshots = _load_snapshot_pool()
        self._opponent_models: dict[str, PPO | None] = {}
        for tid, seat in self.seats.items():
            if seat is self.agent:
                continue
            if snapshots and self._rng.random() < self.opponent_trained_fraction:
                self._opponent_models[tid] = self._rng.choice(snapshots)
            else:
                self._opponent_models[tid] = None

        self.pool = players_in_auction_order(self._pool_source, self._rng)
        self._fair = {p.player_id: fair_price_cr(p) for p in self.pool}
        self._lookahead = PoolLookahead(self.pool, self._fair)
        self._idx = -1
        self._done = False
        # Boost round bookkeeping: players unsold on the main pass, and the
        # index at which the re-auction begins (None until it starts).
        self._unsold: list[AuctionPlayer] = []
        self._boost_start: int | None = None

        self._advance_to_agent_decision()
        return self._obs(), {}

    # -- flow -------------------------------------------------------------

    def _opponent_willingness(self, seat: TeamState, player: AuctionPlayer, fair: float) -> float:
        model = self._opponent_models.get(seat.team_id)
        if model is None:
            return clip_willingness(seat, bot_willingness(seat, player, fair), fair)
        obs = build_observation(
            seat, player, fair,
            same_caliber_left(self.pool[self._idx:], player),
            len(self.pool) - self._idx, len(self.pool),
            self._lookahead.features(self._idx),
            include_pace_spin=self.include_pace_spin,
            team_variant=self.team_variant,
        )
        # Sampled, not argmax: an opponent that always plays its mode is a
        # perfectly predictable clone and trivially exploitable.
        m = multiplier_from_model(model, obs, deterministic=False)
        return clip_willingness(seat, m * fair, fair)

    @property
    def _in_boost_round(self) -> bool:
        return self._boost_start is not None and self._idx >= self._boost_start

    def _current_base_price(self, player: AuctionPlayer) -> float:
        return effective_base_price(player, self._in_boost_round)

    def _resolve_without_agent(self, player: AuctionPlayer, fair: float) -> None:
        base = self._current_base_price(player)
        willingness = {
            tid: self._opponent_willingness(seat, player, fair)
            for tid, seat in self.seats.items()
            if seat is not self.agent
        }
        winner, price = resolve_player(
            player, fair, willingness, self.seats, self._rng, base_price=base
        )
        if winner is not None:
            winner.buy(player, price)
        elif not self._in_boost_round:
            self._unsold.append(player)

    def _start_boost_round_if_due(self) -> bool:
        """Once the main pass is exhausted, re-auction everyone unsold at half
        base price. Returns True if a boost round was opened."""
        if not BOOST_ROUND_ENABLED:
            return False
        if self._boost_start is not None or not self._unsold:
            return False
        if not any(s.slots_remaining > 0 for s in self.seats.values()):
            return False
        self._boost_start = len(self.pool)
        self.pool = self.pool + self._unsold
        self._unsold = []
        return True

    def _advance_to_agent_decision(self) -> None:
        """Fast-forward through every player the agent can't bid on, letting
        the other nine seats resolve them, and stop when the agent actually
        has a decision to make."""
        while True:
            self._idx += 1
            if self._idx >= len(self.pool) and not self._start_boost_round_if_due():
                self._done = True
                return
            if self.agent.slots_remaining <= 0:
                self._done = True
                return
            player = self.pool[self._idx]
            fair = self._fair[player.player_id]
            if self.agent.is_eligible_for(player, self._current_base_price(player)):
                return
            self._resolve_without_agent(player, fair)

    def _obs(self) -> np.ndarray:
        if self._done:
            return np.zeros(obs_dim(self.include_pace_spin), dtype=np.float32)
        player = self.pool[self._idx]
        remaining = self.pool[self._idx:]
        return build_observation(
            self.agent,
            player,
            self._fair[player.player_id],
            same_caliber_left(remaining, player),
            len(remaining),
            len(self.pool),
            self._lookahead.features(self._idx),
            include_pace_spin=self.include_pace_spin,
            team_variant=self.team_variant,
        )

    # -- step -------------------------------------------------------------

    def step(self, action):
        assert not self._done, "step() after episode end -- call reset()"
        player = self.pool[self._idx]
        fair = self._fair[player.player_id]

        base = self._current_base_price(player)
        multiplier = float(np.clip(np.asarray(action).reshape(-1)[0], 0.0, MAX_VALUATION_MULTIPLIER))
        willingness = {self.agent.team_id: clip_willingness(self.agent, multiplier * fair, fair)}
        for tid, seat in self.seats.items():
            if seat is not self.agent:
                willingness[tid] = self._opponent_willingness(seat, player, fair)

        winner, price = resolve_player(
            player, fair, willingness, self.seats, self._rng, base_price=base
        )

        reward = 0.0
        if winner is None and not self._in_boost_round:
            self._unsold.append(player)
        if winner is not None:
            if winner is self.agent:
                # THE reward: what this signing did to the best XI this
                # squad can field. Cannot see price, by construction.
                before = xi_strength(self.agent.squad)
                self.agent.buy(player, price)
                # Marginal XI gain, plus the slot potential: filling a slot
                # pays immediately, at the moment the decision is made.
                reward = xi_strength(self.agent.squad) - before + SLOT_POTENTIAL
            else:
                winner.buy(player, price)

        self._advance_to_agent_decision()
        if self._done:
            reward += self._terminal_reward()
        return self._obs(), float(reward), self._done, False, {}

    def _terminal_reward(self) -> float:
        # Missing slots are charged HERE, terminally -- the per-purchase
        # shaping variant was measured at three magnitudes and abandoned
        # (see SLOT_POTENTIAL). Uses has_legal_xi rather than
        # xi_strength > 0, because xi_strength gives partial credit and is
        # positive for any non-empty squad.
        squad = self.agent.squad
        reward = -(SQUAD_TARGET - len(squad)) * MISSING_SLOT_PENALTY
        if not has_legal_xi(squad):
            reward -= NO_LEGAL_XI_PENALTY
        return reward
