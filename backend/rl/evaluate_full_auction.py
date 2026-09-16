"""
The evaluation that decides whether a model ships: one full auction with
EVERY one of the ten seats driven by the trained policy -- the actual
deployment scenario, not the per-team diagnostic (one learner vs scripted
bots) that training prints, which looked healthy every single time the live
all-AI run was pathological.

Run from backend/ as:
    uv run python -m rl.evaluate_full_auction [model_path] [n_seeds]

WHAT THE GATE IS. The per-purchase detectors, not the z-scores:

    elite_steals -- value_score >= 45 sold under 0.30x fair
    overpays     -- sold above 2.0x fair, plus hard-cap hits
    full_squads / legal_xi
    price/fair median

Those two detectors are OPPOSITE failure modes on the same axis and must be
read together. The cross-team z-score panel below them is diagnostic only,
and there is a specific reason it cannot be the gate: every statistic in it
compares one team against the pooled other nine. When a failure is shared
roughly evenly across all ten teams, the pack IS the failure and z-vs-rest
collapses to ~0 by construction. That happened: a run whose z-scores were
all clean had 22 elite players sold under 0.30x fair across 8 of 10 teams,
visible only on a human read of a second seed. Absolute per-purchase counts
cannot be fooled that way.

This file drives the auction through auction_mdp's own primitives
(players_in_auction_order, build_observation, clip_willingness,
resolve_player) rather than reimplementing them, so evaluation and training
cannot silently diverge -- an earlier hand-rolled re-simulation did diverge
and produced squads the real engine never generated.
"""

from __future__ import annotations

import random
import statistics
import sys
from pathlib import Path

import torch
from scipy import stats
from stable_baselines3 import PPO

from .auction_mdp import (
    BOOST_ROUND_ENABLED,
    MAX_PRICE_TO_FAIR_MULTIPLIER,
    SQUAD_TARGET,
    build_observation,
    clip_willingness,
    effective_base_price,
    multiplier_from_model,
    obs_dim,
    PoolLookahead,
    players_in_auction_order,
    resolve_player,
    same_caliber_left,
)
from .data_loader import load_player_pool, load_team_profiles
from .fair_price import fair_price_cr
from .squad_rules import has_legal_xi, xi_strength
from .team_bot import TeamState

DIR = Path(__file__).resolve().parent
DEFAULT_MODEL_PATH = DIR / "ppo_auction_mdp_v5.zip"
DEFAULT_N_SEEDS = 25

ELITE_VALUE_THRESHOLD = 45.0
ELITE_STEAL_RATIO = 0.30
OVERPAY_RATIO = 2.0


def run_full_ai_auction(model: PPO, seed: int, deterministic: bool = False) -> dict[str, TeamState]:
    """All ten seats bid through the SAME trained policy, each conditioned on
    its own franchise profile.

    STOCHASTIC BY DEFAULT, and that default is load-bearing. Evaluation used
    to take the policy's mean action (deterministic=True), on the assumption
    that the mean is the policy's "best" action. For a Gaussian policy whose
    actions are CLIPPED to [0, 3], that assumption is false: a mean of ~0
    with a wide std behaves like a half-normal and bids perfectly well when
    sampled, while its mean bids nothing at all. PPO has no gradient
    pressure to fix that, because the sampled actions already earn the
    return -- so whether a given run's mean is meaningful is luck.

    Measured on one such run: deterministic play bought 1 player and scored
    -134; the same weights sampled stochastically bought 20 and scored
    +51. Evaluating in a mode the policy never trained in was measuring the
    protocol, not the policy.

    torch is seeded per call so sampled evaluation stays reproducible.
    """
    torch.manual_seed(seed)
    rng = random.Random(seed)
    profiles = {p["team_id"]: p for p in load_team_profiles()}
    seats = {tid: TeamState(tid, profiles[tid], rng) for tid in profiles}

    pool = players_in_auction_order(load_player_pool(), rng)
    fair_by_id = {p.player_id: fair_price_cr(p) for p in pool}

    def run_pass(players: list, is_boost: bool) -> list:
        """One sweep of the auction. Returns whoever went unsold."""
        unsold = []
        # Precomputed once per pass, never per bid -- see PoolLookahead.
        lookahead = PoolLookahead(players, fair_by_id)
        for idx, player in enumerate(players):
            remaining = players[idx:]
            fair = fair_by_id[player.player_id]
            caliber = same_caliber_left(remaining, player)
            base = effective_base_price(player, is_boost)

            willingness = {}
            for tid, seat in seats.items():
                if not seat.is_eligible_for(player, base):
                    continue
                obs = build_observation(
                    seat, player, fair, caliber, len(remaining), len(players),
                    lookahead.features(idx),
                    include_pace_spin=int(model.observation_space.shape[0]) == obs_dim(True),
                )
                m = multiplier_from_model(model, obs, deterministic=deterministic)
                willingness[tid] = clip_willingness(seat, m * fair, fair)

            winner, price = resolve_player(player, fair, willingness, seats, rng, base_price=base)
            if winner is not None:
                winner.buy(player, price)
            else:
                unsold.append(player)
        return unsold

    unsold = run_pass(pool, is_boost=False)
    # Accelerated round, gated by the same flag the training env uses so the
    # two can never disagree about whether it happens (see
    # BOOST_ROUND_ENABLED in auction_mdp.py for why it is currently off).
    if BOOST_ROUND_ENABLED and unsold and any(s.slots_remaining > 0 for s in seats.values()):
        run_pass(unsold, is_boost=True)

    return seats


def report(seats: dict[str, TeamState]) -> None:
    print("=" * 100)
    print(f"{'Team':6s} {'Squad':>6s} {'Spent':>8s} {'PurseLeft':>10s} {'XI':>6s} "
          f"{'Steals':>7s} {'Overpay':>8s}   B/Bo/AR/WK")
    print("-" * 100)
    for tid, seat in seats.items():
        spent = sum(p for _pl, p in seat.bought)
        steals = overpays = 0
        for player, price in seat.bought:
            ratio = price / fair_price_cr(player)
            if player.value_score >= ELITE_VALUE_THRESHOLD and ratio < ELITE_STEAL_RATIO:
                steals += 1
            if ratio > OVERPAY_RATIO:
                overpays += 1
        r = {role: seat.role_count(role) for role in ["Batter", "Bowler", "All-rounder", "Wicketkeeper"]}
        print(f"{tid:6s} {len(seat.squad):6d} {spent:8.2f} {seat.budget:10.2f} "
              f"{xi_strength(seat.squad):6.1f} {steals:7d} {overpays:8d}   "
              f"{r['Batter']}/{r['Bowler']}/{r['All-rounder']}/{r['Wicketkeeper']}")
    print("-" * 100)


def statistical_summary(values_by_team: dict[str, list[float]], metric_name: str) -> dict[str, float]:
    """z-score + Mann-Whitney of each team against the pooled other nine.
    DIAGNOSTIC ONLY -- see the module docstring for why this cannot be the
    gate (a failure shared by all ten teams shows up as z~0)."""
    print("\n" + "=" * 100)
    print(f"CROSS-SEED STATISTICAL SUMMARY ({metric_name})")
    print("=" * 100)
    print(f"{'team':6s} {'mean':>8s} {'std':>8s} {'z-vs-rest':>10s} {'MW p':>8s}  outlier?")

    z_by_team: dict[str, float] = {}
    for tid, values in values_by_team.items():
        others = [v for other, vals in values_by_team.items() if other != tid for v in vals]
        other_std = statistics.pstdev(others)
        z = (statistics.mean(values) - statistics.mean(others)) / other_std if other_std > 0 else 0.0
        _u, p = stats.mannwhitneyu(values, others, alternative="two-sided")
        flag = "  <-- OUTLIER" if abs(z) > 2 and p < 0.05 else ""
        print(f"{tid:6s} {statistics.mean(values):8.2f} {statistics.pstdev(values):8.2f} "
              f"{z:10.2f} {p:8.4f}{flag}")
        z_by_team[tid] = z
    return z_by_team


def flag_consistent_direction(z_by_metric: dict[str, dict[str, float]], threshold: float = 0.3) -> None:
    """A team that never trips |z|>2 on any single metric but sits on the same
    side of zero on EVERY quality metric is a real, small, consistent bias --
    which a single-metric threshold is not built to catch."""
    print("\n" + "=" * 100)
    print(f"CONSISTENT-DIRECTION CHECK (same sign, |z|>{threshold}, across every quality metric)")
    print("=" * 100)
    flagged = False
    for tid in next(iter(z_by_metric.values())):
        zs = [z_by_metric[m][tid] for m in z_by_metric]
        if all(z > threshold for z in zs) or all(z < -threshold for z in zs):
            flagged = True
            direction = "ABOVE" if zs[0] > 0 else "BELOW"
            detail = ", ".join(f"{m}={z:.2f}" for m, z in zip(z_by_metric, zs))
            print(f"{tid:6s} consistently {direction} the pack: {detail}")
    if not flagged:
        print("No team is consistently above or below the pack across all quality metrics.")


def main() -> None:
    model_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MODEL_PATH
    n_seeds = int(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_N_SEEDS
    # Third arg: "deterministic" to play the policy's mean action instead of
    # sampling. Only valid for a policy whose mean is meaningful -- check
    # that before trusting it (see run_full_ai_auction's docstring).
    deterministic = len(sys.argv) > 3 and sys.argv[3].lower().startswith("det")
    mode = "deterministic (mean action)" if deterministic else "stochastic (sampled)"
    print(f"Loading {model_path}... running {n_seeds} seeds, {mode}")
    model = PPO.load(model_path, device="cpu")

    purse_left: dict[str, list[float]] = {}
    xi_by_team: dict[str, list[float]] = {}
    value_by_team: dict[str, list[float]] = {}
    per_cr_by_team: dict[str, list[float]] = {}

    all_ratios: list[float] = []
    elite_steals: list[tuple] = []
    overpays: list[tuple] = []
    cap_hits = 0
    total_purchases = 0
    full_squads = legal_xis = total_seats = 0

    for seed in range(1, n_seeds + 1):
        seats = run_full_ai_auction(model, seed=seed, deterministic=deterministic)
        for tid, seat in seats.items():
            total_seats += 1
            purse_left.setdefault(tid, []).append(seat.budget)
            xi_by_team.setdefault(tid, []).append(xi_strength(seat.squad))
            spend = sum(p for _pl, p in seat.bought)
            total_value = sum(p.value_score for p in seat.squad)
            value_by_team.setdefault(tid, []).append(
                total_value / len(seat.squad) if seat.squad else 0.0
            )
            per_cr_by_team.setdefault(tid, []).append(total_value / spend if spend > 0 else 0.0)

            if len(seat.squad) == SQUAD_TARGET:
                full_squads += 1
            if has_legal_xi(seat.squad):
                legal_xis += 1

            for player, price in seat.bought:
                total_purchases += 1
                fair = fair_price_cr(player)
                ratio = price / fair if fair > 0 else 0.0
                all_ratios.append(ratio)
                if player.value_score >= ELITE_VALUE_THRESHOLD and ratio < ELITE_STEAL_RATIO:
                    elite_steals.append((seed, tid, player, price, fair, ratio))
                if ratio > OVERPAY_RATIO:
                    overpays.append((seed, tid, player, price, fair, ratio))
                if price >= fair * MAX_PRICE_TO_FAIR_MULTIPLIER * 0.95:
                    cap_hits += 1

        if n_seeds <= 3:
            print(f"\n{'#' * 36} seed={seed} {'#' * 36}")
            report(seats)
        else:
            print(f"seed {seed}/{n_seeds} done", flush=True)

    statistical_summary(purse_left, "purse left, Cr")
    xi_z = statistical_summary(xi_by_team, "best legal XI strength, 0-100")
    value_z = statistical_summary(value_by_team, "avg squad value_score, 0-100")
    per_cr_z = statistical_summary(per_cr_by_team, "squad value per Cr spent")
    flag_consistent_direction(
        {"XI strength": xi_z, "avg squad value": value_z, "value per Cr": per_cr_z}
    )

    print("\n" + "=" * 100)
    print("THE GATE -- absolute per-purchase counts, not team-relative")
    print("=" * 100)
    print(f"Elite steals (value>={ELITE_VALUE_THRESHOLD:.0f} under {ELITE_STEAL_RATIO}x fair): "
          f"{len(elite_steals)} / {total_purchases} purchases")
    print(f"Overpays (above {OVERPAY_RATIO}x fair)                     : "
          f"{len(overpays)} / {total_purchases} purchases")
    print(f"Hard-cap hits (>= {MAX_PRICE_TO_FAIR_MULTIPLIER}x fair)                  : "
          f"{cap_hits} / {total_purchases} purchases")
    print(f"Full 20-player squads                            : {full_squads} / {total_seats}")
    print(f"Legal XI                                         : {legal_xis} / {total_seats}")
    if all_ratios:
        print(f"Price/fair ratio  median={statistics.median(all_ratios):.3f}  "
              f"mean={statistics.mean(all_ratios):.3f}  max={max(all_ratios):.3f}")
    else:
        # An untrained (or collapsed) policy whose mean action is ~0 bids
        # below every base price and buys nothing at all. Say so plainly
        # instead of dying in statistics.median on an empty list.
        print("Price/fair ratio  -- NO PURCHASES AT ALL: every seat bid below base price.")

    for label, rows in (("ELITE STEALS", elite_steals), ("OVERPAYS", overpays)):
        if rows:
            worst = sorted(rows, key=lambda r: r[5])[:10] if label == "ELITE STEALS" \
                else sorted(rows, key=lambda r: -r[5])[:10]
            print(f"\nWorst {len(worst)} {label}:")
            for seed, tid, player, price, fair, ratio in worst:
                print(f"  seed={seed:2d} {tid:5s} {player.name:26s} value={player.value_score:5.1f}  "
                      f"{price:6.2f} Cr vs fair {fair:6.2f} Cr ({ratio:.2f}x)")


if __name__ == "__main__":
    main()
