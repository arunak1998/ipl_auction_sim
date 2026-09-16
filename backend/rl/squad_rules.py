"""
What actually makes a squad good: the XI it can put on the field.

The old reward summed value_score over all 20 signings, which made "five
superstars plus fifteen Rs 0.30 Cr fillers" score the same as a balanced
squad -- and, combined with a penalty for leaving money unspent, made
emptying the purse on the first set the genuinely optimal policy. A live
run had 9 of 10 teams spending 64-94% of their purse on their first five
players, and SRH buying seven batters before a single bowler.

Scoring the best legal XI instead fixes both at once: fillers never make the
XI so they add nothing, and a seventh batter is worth nothing once the
batting slots are full. Squad depth still matters (injury/rotation is not
modelled, so the 20-man requirement stays a hard constraint), but quality is
measured where a match is actually won.
"""

from __future__ import annotations

from .data_loader import AuctionPlayer

XI_SIZE = 11
MIN_WICKETKEEPERS = 1
MIN_BATTERS = 4
MIN_BOWLING_OPTIONS = 5  # Bowler or All-rounder -- someone who can bowl overs
MAX_OVERSEAS_IN_XI = 4   # the real IPL playing-XI rule

# An all-rounder satisfies MIN_BOWLING_OPTIONS while also batting, so with only
# that requirement the first trained policy discovered specialist bowlers were
# nearly redundant: every team maxed out at eight all-rounders and SRH fielded
# ONE specialist bowler. Twenty overs need genuine frontline bowling, so a
# minimum number of the bowling slots must be actual bowlers.
MIN_SPECIALIST_BOWLERS = 3

BOWLING_ROLES = ("Bowler", "All-rounder")


def is_bowling_option(player: AuctionPlayer) -> bool:
    return player.role in BOWLING_ROLES


ROLES = ("Wicketkeeper", "Batter", "Bowler", "All-rounder")


def best_xi(squad: list[AuctionPlayer]) -> list[AuctionPlayer] | None:
    """The strongest legal XI this squad can field, or None if it can't field
    one at all (e.g. no keeper, or fewer than five players who can bowl).

    EXACT, not greedy -- and that distinction turned out to matter enormously.

    The previous implementation was greedy by value: satisfy each hard
    minimum with the best available player that doesn't break the overseas
    cap, then fill the rest. Its docstring claimed exact optimisation "isn't
    worth it -- greedy-by-value is optimal or within noise". That was
    asserted, never tested, and it was false. Greedy commits an overseas
    slot to whoever is most valuable for an early requirement (typically a
    star overseas keeper), then runs out of the 4-man overseas XI allowance
    before it can satisfy MIN_SPECIALIST_BOWLERS -- and returns None, i.e.
    "no legal XI", for a squad that demonstrably has one.

    Why that was severe: xi_strength IS the entire reward, and the reward
    for a purchase is xi_strength(after) - xi_strength(before). A
    non-monotonic best_xi therefore paid NEGATIVE reward for a strictly
    improving purchase -- measured at up to -44 (a legal XI of 44.1 dropping
    to 0.0 on signing one more player). Empirically ~3% of late-auction
    purchases were scored this way. A policy that responds by refusing to
    buy late is behaving correctly against a corrupted signal, which is
    exactly what both trained policies did.

    The exact method: adding a player can only ENLARGE the set of legal XIs,
    so a true optimum is monotonic by construction. Enumerate every legal
    split of the 11 places across the four roles, and for each split run a
    tiny DP over how many of the 4 overseas places each role consumes,
    taking the top domestic and top overseas players per role. That is the
    coupling greedy missed. Verified: 0 monotonicity violations over 2002
    squads (greedy had 61), never worse than greedy and strictly better on
    46 of 400 squads, ~0.6ms per call -- and it is only called on a
    purchase (~40 times an episode), so the cost is negligible.
    """
    dom: dict[str, list[AuctionPlayer]] = {r: [] for r in ROLES}
    ovs: dict[str, list[AuctionPlayer]] = {r: [] for r in ROLES}
    for p in squad:
        (ovs if p.is_overseas else dom)[p.role].append(p)
    for r in ROLES:
        dom[r].sort(key=lambda p: -p.value_score)
        ovs[r].sort(key=lambda p: -p.value_score)

    prefix: dict[str, tuple[list[float], list[float]]] = {}
    for r in ROLES:
        cd, co = [0.0], [0.0]
        for p in dom[r]:
            cd.append(cd[-1] + p.value_score)
        for p in ovs[r]:
            co.append(co[-1] + p.value_score)
        prefix[r] = (cd, co)

    def role_value(role: str, n: int, k: int) -> float | None:
        """Total value of taking n players from `role`, exactly k of them
        overseas -- i.e. the top k overseas plus the top n-k domestic."""
        cd, co = prefix[role]
        if k < 0 or n - k < 0 or k >= len(co) or n - k >= len(cd):
            return None
        return co[k] + cd[n - k]

    best_total = -1.0
    best_plan: tuple[dict[str, int], dict[str, int]] | None = None

    for n_wk in range(MIN_WICKETKEEPERS, XI_SIZE + 1):
        for n_bat in range(MIN_BATTERS, XI_SIZE + 1):
            for n_bowl in range(MIN_SPECIALIST_BOWLERS, XI_SIZE + 1):
                n_ar = XI_SIZE - n_wk - n_bat - n_bowl
                if n_ar < 0 or n_bowl + n_ar < MIN_BOWLING_OPTIONS:
                    continue
                counts = {
                    "Wicketkeeper": n_wk, "Batter": n_bat,
                    "Bowler": n_bowl, "All-rounder": n_ar,
                }
                # DP across roles on the shared overseas budget.
                states: dict[int, tuple[float, dict[str, int]]] = {0: (0.0, {})}
                for r in ROLES:
                    nxt: dict[int, tuple[float, dict[str, int]]] = {}
                    for used, (val, picks) in states.items():
                        for k in range(0, min(MAX_OVERSEAS_IN_XI - used, counts[r]) + 1):
                            v = role_value(r, counts[r], k)
                            if v is None:
                                continue
                            total, key = val + v, used + k
                            if key not in nxt or nxt[key][0] < total:
                                nxt[key] = (total, {**picks, r: k})
                    states = nxt
                    if not states:
                        break
                for _used, (total, picks) in states.items():
                    if total > best_total:
                        best_total, best_plan = total, (counts, picks)

    if best_plan is None:
        return None

    counts, picks = best_plan
    chosen: list[AuctionPlayer] = []
    for r in ROLES:
        k = picks[r]
        chosen.extend(ovs[r][:k])
        chosen.extend(dom[r][: counts[r] - k])
    return chosen


def has_legal_xi(squad: list[AuctionPlayer]) -> bool:
    """Can this squad actually field a legal XI? Use THIS for legality --
    not `xi_strength(squad) > 0`, which is now positive for any non-empty
    squad because it gives partial credit (see below)."""
    return best_xi(squad) is not None


def xi_strength(squad: list[AuctionPlayer]) -> float:
    """Strength of the best XI this squad can put out, as a 0-100 score,
    WITH PARTIAL CREDIT for an incomplete squad: fill as many of the eleven
    slots as the squad allows, leave the rest empty, and divide the total by
    eleven. Empty slots score zero.

    BUG FIX -- this was the single most damaging defect in the whole design.
    It used to return the mean of the best LEGAL XI, and 0.0 when no legal
    XI existed. Since the reward is xi_strength(after) - xi_strength(before),
    that made the reward a CLIFF. Measured on a real gate run:

        csk (13 buys): 0,0,0,0,0,0,0,0,0,0,0,0,0
        mi  (16 buys): 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0
        dc  (16 buys): 0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,+40.7

    Two of three teams got ZERO signal from every purchase in the entire
    episode; the third had one purchase carrying all of it. Everything the
    policy did followed from that: race to the eleventh legal player, then
    stop, because nothing after the cliff pays anything -- squads ending at
    16-17 with 21 Cr unspent, purchases compressed into the first third of
    the pool. Adding a forward view of the pool made it WORSE, because a
    better map just finds a faster route to the only payoff there is.

    With partial credit every purchase pays its own marginal value, and
    slots 12-20 still matter because a better player displaces a weaker one
    in the XI. No new reward term, no weights, and price is still nowhere
    near this function.

    Still monotonic by construction, by the same argument as best_xi: a
    larger squad can only widen the choice for every slot, so the optimum
    cannot fall. Note that legality is NOT encoded here any more -- that is
    what has_legal_xi and the terminal NO_LEGAL_XI_PENALTY are for.

    KNOWN PROPERTY (deliberate, not a bug): because a slot may be left
    empty, this can score a complete squad slightly ABOVE the mean of its
    best LEGAL XI -- it may prefer ten strong players to eleven that
    include a weak one forced in by a role minimum under a binding overseas
    cap. Measured at mean +0.68 / max +2.34 on a 36-50 scale, on ~1.5% of
    complete squads, and always in that direction. Forcing a full fill
    instead would make the score able to FALL when a player is added, which
    is precisely the non-monotonicity that made the old greedy best_xi pay
    -44 for a good signing. A small overstatement is much the lesser evil,
    and legality is still enforced separately by NO_LEGAL_XI_PENALTY.
    """
    dom: dict[str, list[AuctionPlayer]] = {r: [] for r in ROLES}
    ovs: dict[str, list[AuctionPlayer]] = {r: [] for r in ROLES}
    for p in squad:
        (ovs if p.is_overseas else dom)[p.role].append(p)
    for r in ROLES:
        dom[r].sort(key=lambda p: -p.value_score)
        ovs[r].sort(key=lambda p: -p.value_score)

    prefix: dict[str, tuple[list[float], list[float]]] = {}
    for r in ROLES:
        cd, co = [0.0], [0.0]
        for p in dom[r]:
            cd.append(cd[-1] + p.value_score)
        for p in ovs[r]:
            co.append(co[-1] + p.value_score)
        prefix[r] = (cd, co)

    best_total = 0.0
    for n_wk in range(MIN_WICKETKEEPERS, XI_SIZE + 1):
        for n_bat in range(MIN_BATTERS, XI_SIZE + 1):
            for n_bowl in range(MIN_SPECIALIST_BOWLERS, XI_SIZE + 1):
                n_ar = XI_SIZE - n_wk - n_bat - n_bowl
                if n_ar < 0 or n_bowl + n_ar < MIN_BOWLING_OPTIONS:
                    continue
                counts = {
                    "Wicketkeeper": n_wk, "Batter": n_bat,
                    "Bowler": n_bowl, "All-rounder": n_ar,
                }
                # DP across roles on the shared overseas budget. Unlike
                # best_xi, a role may contribute FEWER than its slot count
                # when the squad is short -- those slots simply stay empty
                # and contribute nothing, which is what gives partial credit.
                states: dict[int, float] = {0: 0.0}
                for r in ROLES:
                    cd, co = prefix[r]
                    want = counts[r]
                    nxt: dict[int, float] = {}
                    for used, val in states.items():
                        max_ovs = min(MAX_OVERSEAS_IN_XI - used, want, len(co) - 1)
                        for k in range(0, max_ovs + 1):
                            d = min(want - k, len(cd) - 1)
                            total = val + co[k] + cd[d]
                            key = used + k
                            if nxt.get(key, -1.0) < total:
                                nxt[key] = total
                    states = nxt
                best_total = max(best_total, max(states.values(), default=0.0))

    return best_total / XI_SIZE


def role_deficits(squad: list[AuctionPlayer]) -> dict[str, int]:
    """How many more of each requirement this squad still needs for a legal
    XI. Drives both the agent's observation and the 'is this player actually
    useful to me' signal."""
    n_wk = sum(1 for p in squad if p.role == "Wicketkeeper")
    n_bat = sum(1 for p in squad if p.role == "Batter")
    n_bowl = sum(1 for p in squad if is_bowling_option(p))
    n_spec = sum(1 for p in squad if p.role == "Bowler")
    return {
        "Wicketkeeper": max(0, MIN_WICKETKEEPERS - n_wk),
        "Batter": max(0, MIN_BATTERS - n_bat),
        "SpecialistBowler": max(0, MIN_SPECIALIST_BOWLERS - n_spec),
        "BowlingOption": max(0, MIN_BOWLING_OPTIONS - n_bowl),
    }


def min_players_still_needed(squad: list[AuctionPlayer]) -> int:
    """How many more signings this squad genuinely needs to be able to field a
    legal XI.

    NOT sum(role_deficits) -- specialist bowlers are a SUBSET of bowling
    options, so summing double-counts them (an empty squad scores 13 when it
    really needs 10). The endgame eligibility rule keys off this number, and
    the over-count made it fire ~3 slots early, forcing teams to spend their
    whole back end on bowlers and collapsing the learned policy.

    BUG FIX: the role-deficit total alone UNDER-counts, because a legal XI
    needs eleven bodies regardless of how the roles fall. A 3-player squad
    whose roles happen to be well spread reported needing 7 more -- 10 in
    total, one short of an XI it could never field. Found by testing the
    assumption rather than reading the comment above it, prompted by the
    same class of error in best_xi (whose "greedy is optimal or within
    noise" claim was also asserted and also false). The headcount floor is
    now taken explicitly.
    """
    d = role_deficits(squad)
    bowling_needed = max(d["BowlingOption"], d["SpecialistBowler"])
    role_based = d["Wicketkeeper"] + d["Batter"] + bowling_needed
    return max(role_based, XI_SIZE - len(squad))


def fills_a_need(squad: list[AuctionPlayer], player: AuctionPlayer) -> bool:
    d = role_deficits(squad)
    if player.role == "Wicketkeeper" and d["Wicketkeeper"] > 0:
        return True
    if player.role == "Batter" and d["Batter"] > 0:
        return True
    if player.role == "Bowler" and d["SpecialistBowler"] > 0:
        return True
    if is_bowling_option(player) and d["BowlingOption"] > 0:
        return True
    return False
