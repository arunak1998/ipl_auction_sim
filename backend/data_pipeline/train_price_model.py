"""
Phase 2: the actual trained ML model, as opposed to Phase 1's hand-built
percentile formula. Predicts price_pct_of_purse (a player's sale price as a
% of that year's team salary cap) rather than raw Crores, since raw Crore
values aren't comparable across years -- the purse itself grew from ~40.5 Cr
(2011) to ~125 Cr (2026). Salary cap figures are hardcoded below from the
"FX & Purse Reference" sheet in IPL_Auction_Retention_Master_2011_2026.xlsx.

Methodology notes (read before trusting any number this script prints):
  - Evaluation is a TEMPORAL split (train on TRAIN_YEARS, test on
    TEST_YEARS), not a random or player-grouped K-fold. Auction prices
    inflate year over year (the purse itself grew from ~40.5 Cr in 2011 to
    ~125 Cr in 2026, and price_pct_of_purse only normalizes for that, not
    for any other year-over-year drift in bidding behavior); a random or
    GroupKFold split lets the model see 2025/2026-era pricing patterns
    during training and get flatteringly evaluated on more of the same.
    Testing only on the most recent, never-trained-on years is the only
    way to know how this model behaves on the NEXT auction it hasn't seen
    -- which is exactly the deployment scenario (predicting fair prices for
    the CURRENT 620-player pool).
  - A linear Ridge baseline is always reported alongside XGBoost. Given
    only ~650 training rows, a fancier model earning its complexity budget
    is not something to assume -- it has to be shown.
  - Phase 1 (year_cutoff_value_index.py) found real-price correlation
    plateaus around ~0.28 no matter how many stat features are added. This
    script does not expect to blow past that ceiling -- auction price has
    an irreducible component (bidding-war psychology, team-specific need,
    hype) that isn't present in ball-by-ball data. The honest goal here is
    "meaningfully better than Phase 1's fixed formula", not "solved".

Outputs:
  price_model_training_table.csv  -- full feature table used, for audit
  price_model.json                -- trained XGBoost model
  price_model_features.json       -- exact feature list/order + encoders info
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error, r2_score, root_mean_squared_error
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBRegressor

from extract_player_stats import PlayerAccumulator, build_registry, build_stats_row, parse_all_matches
from year_cutoff_value_index import build_bucket_dataframes
from player_value_index import compute_value_scores

DIR = Path(__file__).resolve().parent

# From the "FX & Purse Reference" sheet. 2015/2016 are midpoints of a stated
# range; all other "(indicative)" years give a single figure, used as-is.
SALARY_CAP_CR = {
    2011: 40.50, 2012: 44.10, 2013: 49.05, 2014: 60.00, 2015: 61.50,
    2016: 64.50, 2017: 66.00, 2018: 80.00, 2019: 82.50, 2020: 85.00,
    2021: 85.00, 2022: 90.00, 2023: 95.00, 2024: 100.00, 2025: 120.00,
    2026: 125.00,
}

# Temporal split: test only on the most recent auctions, never seen during
# training. 2025+2026 gives 133 of 672 rows (~20%) -- a real, sizeable test
# set, not a token holdout.
TEST_YEARS = {2025, 2026}

SCORE_FEATURES = [
    "ipl_batting_score", "ipl_bowling_score",
    "intl_t20_batting_score", "intl_t20_bowling_score",
    "other_t20_batting_score", "other_t20_bowling_score",
    "batting_score", "bowling_score", "keeping_score", "value_score",
]
CONTEXT_FEATURES = [
    "ipl_matches_played", "intl_t20_matches_played", "other_t20_matches_played",
    "has_ipl_history", "has_intl_history", "has_other_t20_history",
    "base_price_cr", "prior_price_pct_of_purse", "has_prior_sale",
    "capped", "role_scarcity",
]
# value_score_tier: the tier that actually produced value_score (e.g.
# "IPL/IPL" vs "OTHER_T20/FRINGE") -- a 70 earned in IPL and a 70 earned in
# FRINGE are not the same thing at auction, even though value_score alone
# can't tell them apart. This is genuinely new information the model didn't
# have before the tier system existed.
CATEGORICAL_FEATURES = ["primary_role", "is_overseas", "value_score_tier"]
ALL_NUMERIC_FEATURES = SCORE_FEATURES + CONTEXT_FEATURES


def build_training_table() -> pd.DataFrame:
    print("Parsing all match files...")
    bucket_acc, names_seen = parse_all_matches()
    registry_rows = build_registry(bucket_acc, names_seen)
    registry = pd.DataFrame(registry_rows)
    known_pids = set(registry["player_id"])

    reference_columns = list(build_stats_row("x", "x", "IPL", PlayerAccumulator()).keys())

    auction_df = pd.read_csv(DIR / "ipl_auction_master_with_player_id.csv", dtype={"player_id": str})
    auction_df = auction_df[auction_df["player_id"] != ""].copy()
    auction_df["Year"] = auction_df["Year"].astype(int)
    auction_df = auction_df[auction_df["Year"].isin(SALARY_CAP_CR)]

    rows = []
    for year in sorted(auction_df["Year"].unique()):
        cutoff = f"{year}-01-01"
        bucket_dfs = build_bucket_dataframes(bucket_acc, names_seen, known_pids, reference_columns, cutoff)
        scores = compute_value_scores(bucket_dfs, registry)
        matches_played = {
            b: bucket_dfs[b].set_index("player_id")["matches_played"] if not bucket_dfs[b].empty else pd.Series(dtype=int)
            for b in bucket_dfs
        }

        year_rows = auction_df[auction_df["Year"] == year]
        for _, r in year_rows.iterrows():
            pid = r["player_id"]
            if pid not in scores.index:
                continue
            s = scores.loc[pid]
            row = {"player_id": pid, "player_name": r["Player"], "year": year}
            for col in SCORE_FEATURES:
                row[col] = s.get(col, np.nan)
            for b, key in [("IPL", "ipl_matches_played"), ("INTL_T20", "intl_t20_matches_played"), ("OTHER_T20", "other_t20_matches_played")]:
                row[key] = matches_played[b].get(pid, 0)
            row["has_ipl_history"] = int(row["ipl_matches_played"] > 0)
            row["has_intl_history"] = int(row["intl_t20_matches_played"] > 0)
            row["has_other_t20_history"] = int(row["other_t20_matches_played"] > 0)
            row["primary_role"] = s.get("primary_role", "Unknown")
            country = s.get("country", "")
            row["is_overseas"] = "Unknown" if not isinstance(country, str) or not country else ("No" if country == "India" else "Yes")
            # "Capped" here means the real-world auction rule (uncapped
            # Indian players sit under a base-price ceiling): overseas
            # players aren't subject to that Indian-specific designation at
            # all, so they're treated as capped-equivalent for pricing;
            # for Indian players it's literally "has played international
            # cricket," which has_intl_history already measures directly.
            row["capped"] = 1 if row["is_overseas"] == "Yes" else row["has_intl_history"]
            row["value_score_tier"] = s.get("value_score_tier", None)
            row["base_price_cr"] = r["Base Price (INR Cr)"]
            row["price_cr"] = r["Price / Retention (INR Cr)"]
            row["price_to_base_multiplier"] = r["Price-to-Base Multiplier (x)"]
            row["price_pct_of_purse"] = r["Price / Retention (INR Cr)"] / SALARY_CAP_CR[year] * 100
            rows.append(row)

    table = pd.DataFrame(rows)
    table = table.sort_values(["player_id", "year"])
    table["prior_price_pct_of_purse"] = table.groupby("player_id")["price_pct_of_purse"].shift(1)
    table["has_prior_sale"] = table["prior_price_pct_of_purse"].notna().astype(int)
    table["prior_price_pct_of_purse"] = table["prior_price_pct_of_purse"].fillna(0.0)

    # Scarcity at the position: how many other players of the same role
    # went under the hammer in the SAME auction year -- fewer comparable
    # players pushes price up independent of a player's own skill score.
    table["role_scarcity"] = table.groupby(["year", "primary_role"])["player_id"].transform("count")

    return table


def evaluate(table: pd.DataFrame):
    X_numeric = table[ALL_NUMERIC_FEATURES]
    X_categorical = pd.get_dummies(table[CATEGORICAL_FEATURES], dummy_na=True)
    X = pd.concat([X_numeric, X_categorical], axis=1)
    y = table["price_pct_of_purse"]

    is_test = table["year"].isin(TEST_YEARS)
    train_idx, test_idx = ~is_test, is_test

    print(
        f"\nEvaluating on {len(table)} rows -- temporal split: "
        f"train={train_idx.sum()} rows (years < {min(TEST_YEARS)}), "
        f"test={test_idx.sum()} rows (years {sorted(TEST_YEARS)})\n"
    )

    for name, make_model in [
        ("Ridge (linear baseline)", lambda: make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), Ridge(alpha=5.0))),
        ("XGBoost (shallow, regularized)", lambda: XGBRegressor(
            n_estimators=150, max_depth=3, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_alpha=1.0, reg_lambda=2.0,
            missing=np.nan, random_state=42,
        )),
    ]:
        model = make_model()
        model.fit(X[train_idx], y[train_idx])
        pred = model.predict(X[test_idx])
        mae = mean_absolute_error(y[test_idx], pred)
        rmse = root_mean_squared_error(y[test_idx], pred)
        r2 = r2_score(y[test_idx], pred)
        print(f"{name} (train on years < {min(TEST_YEARS)}, test on {sorted(TEST_YEARS)}):")
        print(f"  MAE  = {mae:.3f}   [price_pct_of_purse units]")
        print(f"  RMSE = {rmse:.3f}")
        print(f"  R2   = {r2:.3f}")

    return X, y


def train_final_model(X: pd.DataFrame, y: pd.Series):
    model = XGBRegressor(
        n_estimators=150, max_depth=3, learning_rate=0.05,
        subsample=0.8, colsample_bytree=0.8, reg_alpha=1.0, reg_lambda=2.0,
        missing=np.nan, random_state=42,
    )
    model.fit(X, y)
    model.save_model(DIR / "price_model.json")
    with open(DIR / "price_model_features.json", "w") as fh:
        json.dump({"feature_columns": list(X.columns)}, fh, indent=2)
    print(f"\nFinal model trained on all {len(X)} rows and saved to price_model.json")

    importances = pd.Series(model.feature_importances_, index=X.columns).sort_values(ascending=False)
    print("\nTop 10 feature importances:")
    print(importances.head(10).to_string())


def main():
    table = build_training_table()
    table.to_csv(DIR / "price_model_training_table.csv", index=False)
    print(f"Saved price_model_training_table.csv: {len(table)} rows")

    X, y = evaluate(table)
    train_final_model(X, y)


if __name__ == "__main__":
    main()
