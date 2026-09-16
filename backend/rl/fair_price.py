"""
Runtime fair-price lookup: what the trained XGBoost price model
(data_pipeline/price_model.json, applied offline by
data_pipeline/compute_fair_prices.py) predicts each player is worth, in
Crore.

This is the single most load-bearing number in the redesigned MDP. The
agent's action is not a bid in rupees -- it's a MULTIPLIER on this price,
so the ML model supplies the units the policy reasons in, and the policy
only has to learn "how much more/less than market is this player worth to
ME", not the absolute price scale. That is the ML model improving the RL:
it removes the entire price-discovery burden from the policy.

No XGBoost in the bidding loop -- the model was applied offline and the
result is a static dict, loaded once and cached.
"""

from __future__ import annotations

import json
from pathlib import Path

from .data_loader import AuctionPlayer

PIPELINE_DIR = Path(__file__).resolve().parents[1] / "data_pipeline"
FAIR_PRICES_JSON = PIPELINE_DIR / "fair_prices.json"

# Nobody in a real auction is worth less than a base-price punt; used only
# for a player the offline pass somehow never scored.
FALLBACK_FLOOR_CR = 0.40

_FAIR_PRICES: dict[str, float] | None = None


def _fair_prices() -> dict[str, float]:
    global _FAIR_PRICES
    if _FAIR_PRICES is None:
        with open(FAIR_PRICES_JSON, encoding="utf-8") as fh:
            _FAIR_PRICES = json.load(fh)
    return _FAIR_PRICES


def fair_price_cr(player: AuctionPlayer) -> float:
    """Model-predicted market price in Crore. Keyed by the POOL id
    ("retained-N"), which is why data_loader must never reorder the CSV."""
    predicted = _fair_prices().get(player.player_id)
    if predicted is None:
        return max(FALLBACK_FLOOR_CR, player.base_price_cr * 1.5)
    return max(FALLBACK_FLOOR_CR, float(predicted))
