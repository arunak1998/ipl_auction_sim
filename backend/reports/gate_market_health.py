"""
The market-health gate. Runs BEFORE any identity diagnostic gets treated as
a pass, because a spinner ratio can improve while the market underneath it
is dead -- that is exactly what happened when pace_spin was first promoted:
ratio 1.11 -> 2.83 looked like a clean win, and the market had collapsed to
22% purse use and 0.18 bids/lot.

TIERED, not aggregated -- on purpose. An aggregate number can look healthy
while one tier has died underneath it, which is precisely how this failure
was missed twice: once by the spinner ratio (an identity metric with no
market-health check at all), and once by an untiered price/fair median
(which the elite tier, still competing normally, would have propped up
while the good tier -- 87.5% zero bids -- pulled the aggregate down only
partially). So price/fair median, bids/lot, AND zero-bid rate are all
reported per value-score tier:

    elite   (value_score >= 65)
    good    (50-64)
    average (35-49)
    weak    (<35)

Purse utilization has no natural per-tier decomposition (it's a whole-
squad number), so it stays a single aggregate figure.

PRE-REGISTERED PASS CRITERIA (fixed before this script was run against the
retrained model, not fitted after seeing results):

    good-tier zero-bid rate   < 50%     (was 87.5% on the collapsed model,
                                          42.9% on baseline)
    good-tier bids/lot        > 2.0     (baseline's own good-tier figure is
                                          5.55; 2.0 is a deliberately weak
                                          bar, "clearly not dead", not "as
                                          good as baseline")
    purse utilization         > 70%     (was 22%, baseline ~89%)

Gated on the GOOD TIER specifically, not an overall/blended bids-per-lot --
an early version of this gate used "overall bids/lot > 3.0" and baseline
ITSELF failed it (2.41), because ~600 weak-tier lots at 98.8% zero-bid
drag any blended average down regardless of what the good tier is doing.
That is the same untiered-aggregate mistake this whole gate exists to
prevent, just relocated into the pass criterion. Caught by validating the
gate against known-healthy baseline BEFORE trusting it on anything new.

The spinner ratio is reported for context but DOES NOT COUNT toward pass or
fail. That is the rule this whole episode exists to establish.

Usage:
    python reports/gate_market_health.py baseline 3
    python reports/gate_market_health.py <your-candidate-tag> 3

To gate a new candidate model, add it to KNOWN_MODELS in
game/model_registry.py first -- see that file's comment on the pattern.
Two prior candidates (pace/spin, star_spend) were gated this way and
rejected; see rl/FINDINGS.md for the numbers.
"""
import statistics as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game.auction_room import AuctionRoom
from game.model_registry import KNOWN_MODELS, ModelRegistry, TEAM_IDS
from rl.fair_price import fair_price_cr

SPIN_LEANING = ["mi", "csk", "rr"]
PACE_LEANING = ["dc", "gt", "lsg"]

TIERS = [
    ("elite (>=65)", 65.0, float("inf")),
    ("good (50-64)", 50.0, 65.0),
    ("average (35-49)", 35.0, 50.0),
    ("weak (<35)", float("-inf"), 35.0),
]

# Pre-registered thresholds. Fixed BEFORE seeing the retrained model's
# numbers -- see module docstring.
PASS_GOOD_TIER_ZERO_RATE_MAX = 0.50
# CORRECTED before ever running against the retrained model: this was
# first written as "overall bids/lot > 3.0", and baseline -- known healthy,
# 88.9% purse use -- FAILED it at 2.41. The weak tier is 608 of ~1294 lots
# at 98.8% zero-bid, which drags any blended average down regardless of
# what the good tier is doing. That is the exact untiered-aggregate
# mistake this gate exists to prevent, just relocated into the pass
# criterion instead of the report. Gating on the GOOD TIER's own bids/lot
# fixes it: baseline's good-tier figure is 5.55; 2.0 sits clearly above
# the collapsed model's near-zero and clearly below baseline, "not dead"
# rather than "as good as baseline".
PASS_GOOD_TIER_BIDS_PER_LOT_MIN = 2.0
PASS_PURSE_UTIL_MIN = 0.70


def tier_of(value_score: float) -> str:
    for name, lo, hi in TIERS:
        if lo <= value_score < hi:
            return name
    return TIERS[-1][0]


def run_one(tag: str, seed: int) -> dict:
    reg = ModelRegistry(tag=tag)
    room = AuctionRoom(TEAM_IDS[0], reg)
    room._rng.seed(seed)

    # Per-lot instrumentation, tiered by the PLAYER UNDER THE HAMMER.
    lot_records = []  # (tier, n_bids, final_price, fair)

    def play_lot_instrumented():
        player = room.current_player
        fair = fair_price_cr(player)
        room.set_auto_bid(0.0)  # human never bids -- isolate AI-vs-AI market health
        n_bids = 0
        stage = 0
        for _ in range(600):
            if stage > 3:
                room.settle_lot()
                break
            evs = room.ai_tick(allow_new_entrant=stage > 0)
            if evs:
                n_bids += 1
                stage = 0
            else:
                stage += 1
        lot_records.append((tier_of(player.value_score), n_bids, room.teams, fair, player))

    while room.get_available_sets():
        room.open_set(room.get_available_sets()[0])
        while room.current_player is not None and room.phase == "AUCTION_STAGE":
            play_lot_instrumented()
    if room.phase == "NOMINATION":
        room.launch_boost_round()
        while room.current_player is not None and room.phase == "BOOST_ROUND":
            play_lot_instrumented()

    # Resolve final prices from the room's own record of who bought whom.
    price_by_player_id = {}
    for tid in TEAM_IDS:
        seat = room.teams[tid]
        for p in seat.squad:
            price_by_player_id[p.player_id] = room._price_paid(seat, p.player_id)

    tiered = {name: {"bids": [], "price_over_fair": [], "zero": 0, "n": 0} for name, _, _ in TIERS}
    for tier, n_bids, _teams, fair, player in lot_records:
        t = tiered[tier]
        t["n"] += 1
        t["bids"].append(n_bids)
        if n_bids == 0:
            t["zero"] += 1
        price = price_by_player_id.get(player.player_id)
        if price is not None and fair > 0:
            t["price_over_fair"].append(price / fair)

    total_spend = sum(125.0 - room.teams[tid].budget for tid in TEAM_IDS)
    purse_util = total_spend / (125.0 * 10)

    # Spinner ratio, for context only -- reported, never gating.
    def spin_share(tid):
        bowlers = [p for p in room.teams[tid].squad if p.role == "Bowler"]
        if not bowlers:
            return None
        return sum(1 for p in bowlers if p.bowler_subtype == "Spin") / len(bowlers)

    s = [x for x in (spin_share(t) for t in SPIN_LEANING) if x is not None]
    p = [x for x in (spin_share(t) for t in PACE_LEANING) if x is not None]
    spinner_ratio = (st.mean(s) / st.mean(p)) if s and p and st.mean(p) > 0 else float("nan")

    # Purse-left by team, ALL 9 AI seats (not just the tiered lots) --
    # tracked because "one franchise finishes 1st one year, 10th the next"
    # turned out to be real and reproducible (see the DC/GT underspend
    # investigation), not a per-team defect visible in any single-lot
    # average. Reported so a future model's underspend-cluster membership
    # has a number to compare against, rather than re-running this whole
    # investigation from scratch.
    purse_left = {tid: room.teams[tid].budget for tid in TEAM_IDS if tid != room.human_team_id}

    return {"tiered": tiered, "purse_util": purse_util, "spinner_ratio": spinner_ratio,
            "purse_left": purse_left}


def main(tag: str, n_seeds: int) -> None:
    entry = KNOWN_MODELS.get(tag)
    if entry is None or not entry["path"].exists():
        print(f"model not found for tag={tag}")
        raise SystemExit(1)
    print(f"model: {entry['path'].name}  (tag={tag})\n")

    all_runs = [run_one(tag, seed) for seed in range(1, n_seeds + 1)]

    print(f"{'tier':18s} {'n lots':>7s} {'zero-bid%':>10s} {'bids/lot':>9s} {'price/fair med':>15s}")
    all_bids = []
    good_zero_rate = None
    good_bids_per_lot = None
    # Per-seed, for the good tier specifically -- this is what the gate
    # actually decides on, so instability here is not optional detail.
    good_zero_per_seed = []
    good_bpl_per_seed = []
    for name, _, _ in TIERS:
        n = sum(r["tiered"][name]["n"] for r in all_runs)
        bids = [b for r in all_runs for b in r["tiered"][name]["bids"]]
        zeros = sum(r["tiered"][name]["zero"] for r in all_runs)
        pof = [x for r in all_runs for x in r["tiered"][name]["price_over_fair"]]
        zero_rate = zeros / n if n else float("nan")
        bpl = st.mean(bids) if bids else float("nan")
        if name == "good (50-64)":
            good_zero_rate = zero_rate
            good_bids_per_lot = bpl
            for r in all_runs:
                t = r["tiered"][name]
                good_zero_per_seed.append(t["zero"] / t["n"] if t["n"] else float("nan"))
                good_bpl_per_seed.append(st.mean(t["bids"]) if t["bids"] else float("nan"))
        all_bids += bids
        print(f"{name:18s} {n:7d} {100*zero_rate:9.1f}% {bpl:9.2f} "
              f"{st.median(pof) if pof else float('nan'):15.2f}")

    purse_utils = [r["purse_util"] for r in all_runs]
    ratios = [r["spinner_ratio"] for r in all_runs]

    def spread_flag(vals: list[float]) -> str:
        """A metric this unstable across seeds is not a number, it's a
        symptom -- print it visibly rather than let a mean hide it. This
        is exactly what happened to the spinner ratio: mean 5.20 read as a
        clear win while the per-seed spread [3.0, 1.84, 10.75] was really
        measuring a market too thin to produce a stable estimate at all."""
        vals = [v for v in vals if v == v]  # drop NaN
        if len(vals) < 2 or min(vals) <= 0:
            return ""
        return "  [UNSTABLE across seeds]" if max(vals) / min(vals) > 2.0 else ""

    print()
    print(f"overall bids/lot        : {st.mean(all_bids):.2f}")
    print(f"purse utilization       : {100*st.mean(purse_utils):.1f}%   "
          f"per-seed {[round(100*x,1) for x in purse_utils]}{spread_flag(purse_utils)}")
    print(f"good-tier zero-bid rate : {100*good_zero_rate:.1f}%   "
          f"per-seed {[round(100*x,1) for x in good_zero_per_seed]}{spread_flag(good_zero_per_seed)}")
    print(f"good-tier bids/lot      : {good_bids_per_lot:.2f}   "
          f"per-seed {[round(x,2) for x in good_bpl_per_seed]}{spread_flag(good_bpl_per_seed)}")
    print(f"spinner ratio (context, does NOT gate): {st.mean(ratios):.2f}   "
          f"per-seed {[round(x,2) for x in ratios]}{spread_flag(ratios)}")

    overall_purse = st.mean(purse_utils)

    print(f"\n{'='*70}")
    print("PRE-REGISTERED GATE (fixed before this run)")
    print(f"  good-tier zero-bid rate  < {100*PASS_GOOD_TIER_ZERO_RATE_MAX:.0f}%  -> "
          f"{100*good_zero_rate:.1f}%  {'PASS' if good_zero_rate < PASS_GOOD_TIER_ZERO_RATE_MAX else 'FAIL'}")
    print(f"  good-tier bids/lot       > {PASS_GOOD_TIER_BIDS_PER_LOT_MIN:.1f}    -> "
          f"{good_bids_per_lot:.2f}  {'PASS' if good_bids_per_lot > PASS_GOOD_TIER_BIDS_PER_LOT_MIN else 'FAIL'}")
    print(f"  purse utilization        > {100*PASS_PURSE_UTIL_MIN:.0f}%   -> "
          f"{100*overall_purse:.1f}%  {'PASS' if overall_purse > PASS_PURSE_UTIL_MIN else 'FAIL'}")
    gate_pass = (good_zero_rate < PASS_GOOD_TIER_ZERO_RATE_MAX
                 and good_bids_per_lot > PASS_GOOD_TIER_BIDS_PER_LOT_MIN
                 and overall_purse > PASS_PURSE_UTIL_MIN)
    print(f"\n  GATE: {'PASS' if gate_pass else 'FAIL'}  "
          f"(spinner ratio {st.mean(ratios):.2f} is reported, not counted)")
    print(f"{'='*70}")

    # TRACKED, NOT GATING. Which franchises end an auction with the most
    # unspent purse, and how often. "DC finishes 1st one year, 10th the
    # next" was real and reproducible (5/10 seeds in the top-2 for DC and
    # GT, 0/10 for MI/RCB/SRH/RR) but invisible in every per-lot average --
    # DC's own mean ceiling ratio was the HIGHEST of the 9 AI teams. This
    # exists so a future model's underspend pattern has a number to
    # compare against instead of re-running that whole investigation.
    print(f"\n{'-'*70}")
    print(f"TRACKED (non-blocking): purse-left rank distribution, {n_seeds} seeds")
    print(f"  rank 1 = most left over that seed")
    rank_sum: dict[str, int] = {}
    top2_count: dict[str, int] = {}
    for r in all_runs:
        ranked = sorted(r["purse_left"].items(), key=lambda kv: -kv[1])
        for rank, (tid, _amt) in enumerate(ranked, 1):
            rank_sum[tid] = rank_sum.get(tid, 0) + rank
        for tid, _amt in ranked[:2]:
            top2_count[tid] = top2_count.get(tid, 0) + 1
    ai_teams = [t for t in TEAM_IDS if t in rank_sum]
    print(f"  {'team':6s} {'top-2-underspend count':>24s} {'mean rank':>10s}")
    for tid in sorted(ai_teams, key=lambda t: -top2_count.get(t, 0)):
        print(f"  {tid:6s} {top2_count.get(tid, 0):24d} {rank_sum[tid]/n_seeds:10.2f}")
    print(f"{'-'*70}")


if __name__ == "__main__":
    tag = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    main(tag, n)
