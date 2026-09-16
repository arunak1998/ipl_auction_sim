"""
Applies the trained XGBoost price model (price_model.json) to the 620 players
in the live auction pool, producing a market fair-price estimate per player.

Why this exists: the price model was trained in Phase 2 and then never used by
anything. The RL agents and the live game were pricing players off
`base_price_cr * team_aggression * role_preference`, which has no idea what a
player is actually worth -- so a 40-value bowler in a team's favourite role
outbid an 85-value player in a role it didn't favour, and marquee players (all
of whom share a nominal Rs 2 Cr base price) were indistinguishable from each
other on price. Anchoring on a real predicted market price fixes both.

The model predicts price_pct_of_purse, so the output is converted to Crores
against the current salary cap. Runs offline; the result is a static lookup
(fair_prices.json) the auction loads at startup -- no XGBoost in the bidding
hot loop.

BUG FIX: this used to carry its own copy of the surname+initials name-matching
heuristic to find each auction player's registry row -- the exact same
"reg_initials[0] == given_initials[0]" bug already found and fixed in
rl/data_loader.py (see build_player_id_map.py's docstring for the full story:
it silently collapsed distinct players sharing a surname and first initial,
e.g. Rohit Sharma vs Rituraj Sharma). Since this file's output feeds directly
into fair_price_cr(), which the RL policy consumes on every bid decision, a
wrong match here poisoned the exact signal the whole redesign was for. Now
joins on player_id via player_id_map_final.csv -- the same one-time,
human-reviewed map data_loader.py uses -- not a runtime name heuristic.

Run from backend/ as:  uv run python -m data_pipeline.compute_fair_prices
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from rl.data_loader import load_player_pool

from .player_value_index import BUCKET_TIERS, BUCKET_WEIGHTS

DIR = Path(__file__).resolve().parent
CURRENT_SALARY_CAP_CR = 125.00

# Mirrors train_price_model.SALARY_CAP_CR -- duplicated rather than imported
# because that module pulls in the whole Cricsheet YAML parsing pipeline.
SALARY_CAP_CR = {
    2011: 40.50, 2012: 44.10, 2013: 49.05, 2014: 60.00, 2015: 61.50,
    2016: 64.50, 2017: 66.00, 2018: 80.00, 2019: 82.50, 2020: 85.00,
    2021: 85.00, 2022: 90.00, 2023: 95.00, 2024: 100.00, 2025: 120.00,
    2026: 125.00,
}

# The model was trained on transactions where a "cheap" player still went for
# something; a player it has never seen (no registry match, no history) gets
# this floor rather than a meaningless extrapolation.
FALLBACK_FAIR_PRICE_CR = 0.40

# All tier labels the price model was trained to recognize, derived straight
# from the same declarative tier list player_value_index.py uses -- adding a
# tier there means it shows up here automatically, no separate list to keep
# in sync.
ALL_TIER_LABELS = [f"{b}/{t['name']}" for b in BUCKET_WEIGHTS for t in BUCKET_TIERS[b]]


def load_matches_played() -> dict[str, pd.Series]:
    out = {}
    for key, fname in [
        ("ipl", "ipl_stats.csv"),
        ("intl_t20", "international_t20_stats.csv"),
        ("other_t20", "other_t20_stats.csv"),
    ]:
        df = pd.read_csv(DIR / fname, dtype={"player_id": str})
        out[key] = df.set_index("player_id")["matches_played"]
    return out


def load_prior_sales() -> pd.Series:
    """Most recent observed sale for each player, as % of that year's purse --
    the model's `prior_price_pct_of_purse` feature."""
    df = pd.read_csv(DIR / "ipl_auction_master_with_player_id.csv", dtype={"player_id": str})
    df = df[df["player_id"].notna() & (df["player_id"] != "")].copy()
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce")
    df = df[df["Year"].isin(SALARY_CAP_CR)]
    df["price_pct"] = df.apply(
        lambda r: r["Price / Retention (INR Cr)"] / SALARY_CAP_CR[int(r["Year"])] * 100, axis=1
    )
    latest = df.sort_values("Year").groupby("player_id")["price_pct"].last()
    return latest


def main() -> None:
    players = load_player_pool()
    id_map = pd.read_csv(DIR / "player_id_map_final.csv", dtype=str)
    player_id_by_name = dict(zip(id_map["auction_name"], id_map["player_id"]))

    value_index = pd.read_csv(DIR / "player_value_index.csv", dtype={"player_id": str})
    vi = value_index.set_index("player_id")
    matches = load_matches_played()
    prior_sales = load_prior_sales()

    # Scarcity at the position: how many players of the same role are in
    # THIS pool -- the live-deployment equivalent of train_price_model's
    # "how many sold in the same auction year," since the current pool
    # itself is what a bidder is choosing among.
    role_counts: dict[str, int] = {}
    for p in players:
        role_counts[p.role] = role_counts.get(p.role, 0) + 1

    feature_columns = json.loads((DIR / "price_model_features.json").read_text())["feature_columns"]

    rows = []
    matched_count = 0
    for p in players:
        rid = player_id_by_name.get(p.name)
        if rid is not None and rid in vi.index:
            matched_count += 1
            s = vi.loc[rid]
            if isinstance(s, pd.DataFrame):  # duplicate registry ids -- take first
                s = s.iloc[0]
            scores = {c: float(s.get(c, np.nan)) for c in [
                "ipl_batting_score", "ipl_bowling_score",
                "intl_t20_batting_score", "intl_t20_bowling_score",
                "other_t20_batting_score", "other_t20_bowling_score",
                "batting_score", "bowling_score", "keeping_score",
            ]}
            value_score_tier = s.get("value_score_tier")
            ipl_m = float(matches["ipl"].get(rid, 0) or 0)
            intl_m = float(matches["intl_t20"].get(rid, 0) or 0)
            other_m = float(matches["other_t20"].get(rid, 0) or 0)
            prior = float(prior_sales.get(rid, 0.0) or 0.0)
        else:
            scores = {c: np.nan for c in [
                "ipl_batting_score", "ipl_bowling_score",
                "intl_t20_batting_score", "intl_t20_bowling_score",
                "other_t20_batting_score", "other_t20_bowling_score",
                "batting_score", "bowling_score", "keeping_score",
            ]}
            value_score_tier = None
            ipl_m = intl_m = other_m = 0.0
            prior = 0.0

        row = dict(scores)
        row["value_score"] = float(p.value_score)
        row["ipl_matches_played"] = ipl_m
        row["intl_t20_matches_played"] = intl_m
        row["other_t20_matches_played"] = other_m
        row["has_ipl_history"] = int(ipl_m > 0)
        row["has_intl_history"] = int(intl_m > 0)
        row["has_other_t20_history"] = int(other_m > 0)
        row["base_price_cr"] = float(p.base_price_cr)
        row["prior_price_pct_of_purse"] = prior
        row["has_prior_sale"] = int(prior > 0)
        # Real capped/uncapped label from the current pool -- train time
        # only had a proxy (overseas, or has_intl_history for Indians)
        # since the historical auction data carries no such column, but at
        # inference the real thing is directly available on AuctionPlayer.
        row["capped"] = int(p.capped)
        row["role_scarcity"] = role_counts[p.role]

        # one-hot blocks, matching the dummy columns the model was trained on
        for r in ["All-rounder", "Batter", "Bowler", "Wicketkeeper"]:
            # training used the registry's label set ("All-Rounder" style)
            key = {"All-rounder": "All-Rounder"}.get(r, r)
            row[f"primary_role_{key}"] = int(p.role == r)
        row["primary_role_nan"] = 0
        row["is_overseas_Yes"] = int(p.is_overseas)
        row["is_overseas_No"] = int(not p.is_overseas)
        row["is_overseas_Unknown"] = 0
        row["is_overseas_nan"] = 0
        for label in ALL_TIER_LABELS:
            row[f"value_score_tier_{label}"] = int(value_score_tier == label)
        row["value_score_tier_nan"] = int(value_score_tier is None or (isinstance(value_score_tier, float) and np.isnan(value_score_tier)))

        row["_player_id"] = p.player_id
        row["_name"] = p.name
        row["_matched"] = rid is not None
        rows.append(row)

    table = pd.DataFrame(rows)
    X = pd.DataFrame({c: table[c] if c in table.columns else 0.0 for c in feature_columns})

    model = XGBRegressor()
    model.load_model(DIR / "price_model.json")
    pred_pct = model.predict(X)

    fair_cr = np.clip(pred_pct, 0.0, None) / 100.0 * CURRENT_SALARY_CAP_CR

    # The model only ever saw players somebody actually bought, so it has no
    # concept of a player worth less than ~3 Cr and floors there. For anyone we
    # couldn't match to real career stats (no registry entry -> value_score is
    # the capped/uncapped default, not a measured number) that floor is
    # meaningless, so anchor them to their own base price instead -- which is
    # exactly what a real squad-filler goes for.
    unmatched = ~table["_matched"].to_numpy()
    base_anchor = table["base_price_cr"].to_numpy() * 1.5
    fair_cr = np.where(unmatched, base_anchor, fair_cr)
    fair_cr = np.maximum(fair_cr, FALLBACK_FAIR_PRICE_CR)

    out = {table["_player_id"].iloc[i]: round(float(fair_cr[i]), 3) for i in range(len(table))}
    (DIR / "fair_prices.json").write_text(json.dumps(out, indent=2))

    table["fair_price_cr"] = fair_cr
    print(f"Players: {len(table)}   matched to registry: {matched_count}   unmatched: {len(table)-matched_count}")
    print(f"fair price Cr -- min={fair_cr.min():.2f} median={np.median(fair_cr):.2f} "
          f"mean={fair_cr.mean():.2f} max={fair_cr.max():.2f}")
    print("\nTop 15 by predicted fair price:")
    for _, r in table.nlargest(15, "fair_price_cr").iterrows():
        print(f"  {r['fair_price_cr']:6.2f} Cr  {r['_name']:28s} value={r['value_score']:5.1f} base={r['base_price_cr']:.2f}")
    print("\nBottom 5:")
    for _, r in table.nsmallest(5, "fair_price_cr").iterrows():
        print(f"  {r['fair_price_cr']:6.2f} Cr  {r['_name']:28s} value={r['value_score']:5.1f} base={r['base_price_cr']:.2f}")
    print(f"\nWrote {DIR / 'fair_prices.json'}")


if __name__ == "__main__":
    main()
