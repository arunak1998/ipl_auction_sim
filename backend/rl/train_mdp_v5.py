"""
Trains the v5 valuation policy: one shared, FiLM-conditioned network that
plays all ten franchises, across an annealing self-play curriculum.

Run from backend/ as:  uv run python -m rl.train_mdp_v5

Curriculum: phase 0 is pure scripted-bot training, so there is a sane
policy to snapshot before self-play begins at all (starting self-play from
a random-init policy is just two random policies bidding at each other).
Each later phase raises opponent_trained_fraction and draws opponents from
a rotating pool of recent snapshots -- a pool, not just the latest
checkpoint, so the policy can't overfit to one specific opponent version.
It never reaches 100% self-play: scripted "flawed toy" archetypes stay in
the mix throughout, which is what keeps the policy robust to opponents
that are not near-copies of itself.

gamma=0.999 is safe here in a way it was not in the old per-increment
design: an episode is ~60-130 decisions, not ~700, so 0.999^130 ~= 0.88 --
the terminal squad-completion and legal-XI penalties arrive essentially
undiscounted at the moment the policy is choosing its early bids.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO
from stable_baselines3.common.env_util import make_vec_env
from stable_baselines3.common.monitor import Monitor

from rl.auction_mdp import SNAPSHOT_POOL_DIR, AuctionMDPEnv
from rl.data_loader import load_team_profiles
from rl.film_policy import FiLMFeaturesExtractor
from rl.squad_rules import xi_strength

DIR = Path(__file__).resolve().parent

# An optional tag on the command line keeps an experiment OFF the live
# model: `python -m rl.train_mdp_v5 pace_spin` writes
# ppo_auction_mdp_v5_pace_spin.zip and leaves ppo_auction_mdp_v5.zip --
# the file game/model_registry.py loads -- exactly where it is.
TAG = sys.argv[1] if len(sys.argv) > 1 else ""
_suffix = f"_{TAG}" if TAG else ""
MODEL_PATH = DIR / f"ppo_auction_mdp_v5{_suffix}.zip"
SUMMARY_PATH = DIR / f"training_summary_v5{_suffix}.json"

# Which observation shape this run trains on. Only "pace_spin" opts in --
# every other tag (including "", the live model) trains on the baseline
# 45-dim shape, so re-running the plain command never silently changes
# what the live model expects.
INCLUDE_PACE_SPIN = TAG == "pace_spin"
TEAM_VARIANT = "star_spend" if TAG == "star_spend" else "baseline"

N_ENVS = 8
SNAPSHOT_POOL_MAX_SIZE = 4
EVAL_EPISODES_PER_TEAM = 5

# Lowered from SB3's usual 0.01 after a run collapsed to a MEANINGLESS MEAN.
# The action is a single valuation multiplier clipped to [0, 3]. A Gaussian
# centred near 0 with a wide std therefore acts like a half-normal: sampled
# play bids fine and earns the return, so PPO feels no gradient pressure to
# raise the mean -- while the entropy bonus actively pushes std UP. One run
# ended with std=1.35 and a mean action of ~0.009: sampled it bought 20
# players and scored +51, but played at its mean it bought ONE and scored
# -134. Whether a run's mean was usable was luck, which silently corrupted
# every model-vs-model comparison made under deterministic evaluation.
# A smaller entropy bonus (with log_std_init below) keeps the distribution
# tight enough that the mean is the policy.
ENT_COEF = 0.001

CURRICULUM = [
    (0.0, 200_000),
    (0.15, 200_000),
    (0.30, 200_000),
    (0.45, 200_000),
    (0.60, 200_000),
    (0.75, 200_000),
    # PERMANENT, regardless of what any single model does with it. Added
    # after the pace/spin promotion collapsed the live market: every seat
    # deployed is 10/10 copies of this policy, a condition the curriculum
    # never trained at before (0.75 was the ceiling) -- the same v3->v4
    # train/deploy gap this project fixed once already, re-opened. Scripted
    # bots are NOT removed from the mix here or in any earlier phase --
    # they stay, per this file's own robustness rationale (flawed-toy
    # opponents). Both new phases are ADDED on top of the existing ramp.
    #
    # MEASURED, not assumed: on the pace_spin retrain, ONE 200k phase at
    # 1.0 took the good-tier (value_score 50-64) market from total
    # collapse to real activity --
    #     good-tier bids/lot     0.00 -> 1.08
    #     good-tier zero-bid%     100% -> 82.4%
    #     purse utilization      21.9% -> 55.7%
    #     elite-tier bids/lot     0.66 -> 13.73   (close to baseline's 16.92)
    # -- from a single phase, against a curriculum that had never included
    # this condition at all. That is the deployment condition finally
    # appearing during training, not a pace/spin-specific effect, so every
    # future model trained on this curriculum benefits from it.
    (0.90, 200_000),
    (1.00, 400_000),
]


def make_env(opponent_trained_fraction: float):
    def _make():
        return Monitor(AuctionMDPEnv(
            opponent_trained_fraction=opponent_trained_fraction,
            include_pace_spin=INCLUDE_PACE_SPIN,
            team_variant=TEAM_VARIANT,
        ))
    return _make


def _prune_snapshot_pool() -> None:
    snapshots = sorted(SNAPSHOT_POOL_DIR.glob("*.zip"), key=lambda p: p.stat().st_mtime)
    for stale in snapshots[:-SNAPSHOT_POOL_MAX_SIZE]:
        stale.unlink()


def train() -> PPO:
    SNAPSHOT_POOL_DIR.mkdir(exist_ok=True)
    # Clear snapshots from any previous run -- otherwise phase 0 (which never
    # reads the pool) would still leave an older run's policies sitting there
    # for phase 1 to train against.
    for stale in SNAPSHOT_POOL_DIR.glob("*.zip"):
        stale.unlink()

    model: PPO | None = None
    policy_kwargs = {
        "features_extractor_class": FiLMFeaturesExtractor,
        "features_extractor_kwargs": {"features_dim": 64},
        # log_std_init=-1.0 => initial action std ~0.37, not the SB3 default
        # of 1.0. See ENT_COEF below for why this matters: with actions
        # clipped to [0, 3], a wide Gaussian centred at 0 behaves like a
        # half-normal, bids perfectly well when SAMPLED, and leaves the mean
        # action meaningless. A tighter initial spread forces the mean to
        # carry the policy from the start.
        "log_std_init": -1.0,
    }

    for phase_idx, (fraction, steps) in enumerate(CURRICULUM):
        print(f"\n=== Phase {phase_idx}: opponent_trained_fraction={fraction}, {steps:,} steps ===")
        env = make_vec_env(make_env(fraction), n_envs=N_ENVS)

        if model is None:
            model = PPO(
                "MlpPolicy", env, verbose=1,
                learning_rate=3e-4, n_steps=512, batch_size=128,
                gamma=0.999, gae_lambda=0.95, ent_coef=ENT_COEF, seed=42,
                policy_kwargs=policy_kwargs,
            )
        else:
            model.set_env(env)

        model.learn(total_timesteps=steps, reset_num_timesteps=False, progress_bar=False)

        snapshot = SNAPSHOT_POOL_DIR / f"phase{phase_idx}.zip"
        model.save(snapshot)
        _prune_snapshot_pool()
        print(f"Phase {phase_idx} snapshot saved -> {snapshot}")

    model.save(MODEL_PATH)
    return model


def run_episode(model: PPO, team_id: str, seed: int) -> dict:
    env = AuctionMDPEnv(
        agent_team_id=team_id, seed=seed,
        include_pace_spin=INCLUDE_PACE_SPIN, team_variant=TEAM_VARIANT,
    )
    obs, _ = env.reset(seed=seed)
    total = 0.0
    while True:
        action, _ = model.predict(obs, deterministic=True)
        obs, r, term, trunc, _ = env.step(action)
        total += r
        if term or trunc:
            break
    a = env.agent
    return {
        "reward": total,
        "squad": len(a.squad),
        "budget_left": a.budget,
        "xi_strength": xi_strength(a.squad),
    }


def evaluate_per_team(model: PPO) -> dict:
    """Quick diagnostic only (one learner vs scripted bots). The real gate is
    rl/evaluate_full_auction.py, where all ten seats are AI-driven."""
    summary = {}
    for profile in load_team_profiles():
        tid = profile["team_id"]
        results = [run_episode(model, tid, seed=3000 + i) for i in range(EVAL_EPISODES_PER_TEAM)]
        summary[tid] = {
            "avg_reward": float(np.mean([r["reward"] for r in results])),
            "avg_squad": float(np.mean([r["squad"] for r in results])),
            "avg_budget_left": float(np.mean([r["budget_left"] for r in results])),
            "avg_xi_strength": float(np.mean([r["xi_strength"] for r in results])),
        }
    return summary


def main() -> None:
    total = sum(s for _f, s in CURRICULUM)
    print(f"Training v5: {len(CURRICULUM)} phases, {total:,} total steps, {N_ENVS} envs")
    model = train()
    print(f"\nSaved -> {MODEL_PATH}")

    print("\n--- Per-team isolated eval (diagnostic, NOT the gate) ---")
    summary = evaluate_per_team(model)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
    print(f"{'team':6s} {'reward':>8s} {'squad':>6s} {'purse_left':>11s} {'XI':>6s}")
    for tid, s in summary.items():
        print(f"{tid:6s} {s['avg_reward']:8.2f} {s['avg_squad']:6.1f} "
              f"{s['avg_budget_left']:11.2f} {s['avg_xi_strength']:6.1f}")
    print(f"Summary -> {SUMMARY_PATH}")


if __name__ == "__main__":
    main()
