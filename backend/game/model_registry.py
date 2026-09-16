"""
Loads the trained v4 auction policy once at server startup.

v1/v2 (superseded): one PPO model PER team. v3 moved to a SINGLE shared,
team-conditioned policy (rl/train_mdp.py) -- one network expresses all ten
identities via team profile features in the observation. v4
(rl/train_mdp_v4.py) keeps that architecture and adds: a self-play opponent
pool (v3 trained against scripted bots only, then got deployed with all 10
seats running that same policy -- an opponent distribution it never saw,
which produced runaway ~110 Cr single-player bids in a live 10-team test);
FiLM team-conditioning (rl/film_policy.py) instead of flat concatenation,
for real differentiation between teams instead of one dominant modal squad
shape; budget-pacing and Fast/Spin-bowler reward terms. See
rl/auction_mdp.py's module docstring and rl/evaluate_full_auction.py for
the full story and the evaluation harness that validates it.

Loading requires rl.film_policy to be importable (PPO.load reconstructs the
custom FiLMFeaturesExtractor from its saved class path) -- it always is,
since it's a real module in this same backend package.
"""

from pathlib import Path

from stable_baselines3 import PPO

# Imported for its side effect of registering FiLMFeaturesExtractor at the
# same module path the saved model expects to find it at.
from rl import film_policy  # noqa: F401
from rl.auction_mdp import multiplier_from_model

RL_DIR = Path(__file__).resolve().parents[1] / "rl"
MODEL_PATH = RL_DIR / "ppo_auction_mdp_v5.zip"

TEAM_IDS = ["csk", "mi", "rcb", "kkr", "srh", "rr", "dc", "pbks", "gt", "lsg"]

# Every model file this project knows about, and the exact observation
# shape each one was trained on. This is the SINGLE SOURCE OF TRUTH a tag
# maps to -- deliberately not shape-inferred, because "baseline" and
# "star_spend" are BOTH 45-dim (star_spend swaps the team block's CONTENT,
# not its size). Two different models sharing one shape is exactly the
# case shape-inference cannot catch, so a tag is looked up here instead of
# guessed from the file.
KNOWN_MODELS: dict[str, dict] = {
    # 2026-09-15: promoted ppo_auction_mdp_v5_pace_spin.zip to live on a
    # spinner ratio of 1.11 -> 2.83, then REVERTED to baseline the same day
    # once the full picture came in. See reports/gate_market_health.py's
    # docstring for the whole story; short version --
    #
    #   pace/spin's identity gain was a market-collapse artefact, not a
    #   real effect. Deployed, the model dropped purse use to 22% and the
    #   good tier (value_score 50-64) to 100% zero-bid lots. Four
    #   escalating fixes (bid noise, then a permanent 0.90->1.00/400k
    #   curriculum addition) recovered the market to 74% purse use and
    #   77.3% good-tier zero-bid -- and as the market recovered, the
    #   spinner ratio walked back down with it: 2.83 -> 5.20 (unstable,
    #   [3.0, 1.84, 10.75]) -> 1.21, converging on baseline's own 1.11.
    #   The identity gain never existed independent of the collapse that
    #   produced it. star_spend (the team-side identity feature) was
    #   measured on the same gate and came back weak on its own terms
    #   (0.79 -> 1.05, 1.02 -> 1.12) -- both team-conditioned identity
    #   attempts failed; neither is shipped.
    #
    #   KEPT, permanently: the 0.90/1.00 curriculum phases in
    #   train_mdp_v5.py (closes a real train/deploy gap, independent of
    #   pace/spin -- elite bids/lot 0.66 -> 13.73 on the 1.0 phase alone)
    #   and this tiered market-health gate itself, which caught its own
    #   aggregation bug and a 5.20 headline number that was noise.
    #
    # Live is baseline: rl/baseline/ppo_auction_mdp_v5_BASELINE.zip.
    "live": {"path": MODEL_PATH, "include_pace_spin": False, "team_variant": "baseline"},
    "baseline": {
        "path": RL_DIR / "baseline" / "ppo_auction_mdp_v5_BASELINE.zip",
        "include_pace_spin": False, "team_variant": "baseline",
    },
    # To gate a new candidate model: drop its .zip anywhere under rl/, add
    # one entry here with the right (include_pace_spin, team_variant) for
    # how it was trained, then run e.g.
    #   python reports/gate_market_health.py <tag> 3
    # before ever touching MODEL_PATH. Two prior candidates (pace/spin
    # player-side features, team-side star-spend features) were built,
    # measured this way, and rejected -- see rl/FINDINGS.md for the full
    # numbers and reasoning, not repeated here since their weight files
    # are no longer kept on disk.
}


class ModelRegistry:
    def __init__(self, model_path: Path | None = None, tag: str | None = None):
        """Two ways in, one always safe:

        No args -> the live game's path exactly as before. tag="..." looks
        up KNOWN_MODELS, which is the ONLY way to select a non-baseline
        team_variant (see the module note on why that can't be inferred
        from shape). model_path=... stays for ad hoc use and infers
        include_pace_spin from shape, team_variant always "baseline" --
        correct for every model that currently exists at an arbitrary path.
        """
        if tag is not None:
            entry = KNOWN_MODELS[tag]
            path = entry["path"]
            self._include_pace_spin = entry["include_pace_spin"]
            self._team_variant = entry["team_variant"]
        else:
            path = model_path or MODEL_PATH
            self._team_variant = "baseline"
            self._include_pace_spin = None  # resolved lazily below, needs self._model

        self._model = PPO.load(path, device="cpu") if path.exists() else None

        if self._include_pace_spin is None:
            from rl.auction_mdp import obs_dim
            self._include_pace_spin = (
                self._model is not None
                and int(self._model.observation_space.shape[0]) == obs_dim(True)
            )

    def has_model(self, team_id: str) -> bool:
        return self._model is not None

    def include_pace_spin(self) -> bool:
        return self._include_pace_spin

    def team_variant(self) -> str:
        return self._team_variant

    def version_of(self, team_id: str) -> str | None:
        return "v5" if self._model is not None else None

    def willingness_multiplier(self, observation) -> float:
        """How much this team values the player, as a MULTIPLE of the price
        model's fair price -- 0 means "not interested", 1.0 means "worth
        market rate to me", 2.5 means "I want him badly".

        This replaced a boolean decide() when the policy moved from a
        per-increment BID/PASS action space to a single valuation per
        player. The observation must be built by
        rl/auction_mdp.build_observation, or the policy is being fed
        nonsense.
        """
        return multiplier_from_model(self._model, observation, deterministic=True)
