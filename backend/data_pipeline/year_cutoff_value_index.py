"""
Fixes the Phase 1 price calibration by computing each player's Value Score
AS OF each historical auction year (using only stats from matches strictly
before that year), instead of comparing today's career-to-date score against
decade-old prices -- which is what caused the earlier flat, compressed
calibration (0.26 correlation).

Assumption (stated plainly, not hidden): cutoff for auction year Y is
"Y-01-01" -- i.e. a player's Y-auction score uses every match dated before
Jan 1 of year Y. Real auctions happen in Nov/Dec of the prior year or early
in year Y itself, so this is a reasonable, simple line to draw.

Known simplification: primary_role (Batter/Bowler/All-rounder/Wicketkeeper)
is taken from the full-career registry, not re-derived per year-cutoff. A
player's fundamental skill type essentially never changes mid-career, so
this avoids a second layer of per-year classification without materially
affecting the result -- but it is a simplification, not re-derived data.

Known simplification: teams_played_for / competitions_played are kept as
full-career values in the cutoff snapshot (not date-filtered) since they're
descriptive only and don't feed the score calculation itself.

Outputs:
  year_cutoff_qualifying_counts.csv   -- real count of players scored per year
  year_cutoff_calibration_pairs.csv   -- every (year, player, score-at-time,
                                          real price-at-time) pair used
  player_value_index.csv              -- estimated_price_cr recalibrated
                                          using the pooled year-cutoff pairs
"""

from pathlib import Path

import pandas as pd

from extract_player_stats import BUCKETS, PlayerAccumulator, build_registry, build_stats_row, parse_all_matches, write_csv
from player_value_index import compute_value_scores

DIR = Path(__file__).resolve().parent

YEARS = range(2011, 2027)


def filter_accumulator(acc: PlayerAccumulator, cutoff: str) -> PlayerAccumulator | None:
    dates = [d for d in acc.match_dates if d < cutoff]
    if not dates:
        return None
    return PlayerAccumulator(
        name=acc.name,
        batting=[b for b in acc.batting if b.match_date < cutoff],
        bowling=[b for b in acc.bowling if b.match_date < cutoff],
        catches=[d for d in acc.catches if d < cutoff],
        run_outs=[d for d in acc.run_outs if d < cutoff],
        stumpings=[d for d in acc.stumpings if d < cutoff],
        teams=acc.teams,
        competitions=acc.competitions,
        match_dates=dates,
    )


def build_bucket_dataframes(
    bucket_acc: dict[str, dict[str, PlayerAccumulator]],
    names_seen: dict[str, str],
    known_pids: set[str],
    reference_columns: list[str],
    cutoff: str | None,
) -> dict[str, pd.DataFrame]:
    """cutoff=None means no filtering (today's full career-to-date stats)."""
    bucket_dfs = {}
    for b in BUCKETS:
        rows = []
        for pid, acc in bucket_acc[b].items():
            if pid not in known_pids:
                continue
            if cutoff is not None:
                acc = filter_accumulator(acc, cutoff)
                if acc is None:
                    continue
            rows.append(build_stats_row(pid, names_seen.get(pid, ""), b, acc))
        bucket_dfs[b] = pd.DataFrame(rows, columns=reference_columns)
    return bucket_dfs


def main():
    print("Parsing all match files (one pass, reused for every year cutoff)...")
    bucket_acc, names_seen = parse_all_matches()

    registry_rows = build_registry(bucket_acc, names_seen)
    registry = pd.DataFrame(registry_rows)
    known_pids = set(registry["player_id"])

    # Derive the current schema directly from build_stats_row itself (not from
    # the on-disk CSVs, which would go stale the moment a field is added/changed).
    dummy = PlayerAccumulator(name="dummy")
    reference_columns = list(build_stats_row("dummy", "dummy", "IPL", dummy).keys())

    auction_df = pd.read_csv(DIR / "ipl_auction_master_with_player_id.csv", dtype={"player_id": str})

    print("Refreshing ipl_stats.csv / international_t20_stats.csv / other_t20_stats.csv / players_registry.csv with the current schema...")
    write_csv(DIR / "players_registry.csv", registry_rows)
    today_bucket_dfs = build_bucket_dataframes(bucket_acc, names_seen, known_pids, reference_columns, cutoff=None)
    filenames = {"IPL": "ipl_stats.csv", "INTL_T20": "international_t20_stats.csv", "OTHER_T20": "other_t20_stats.csv"}
    for b in BUCKETS:
        today_bucket_dfs[b].to_csv(DIR / filenames[b], index=False)

    qualifying_counts = []
    calibration_pairs = []

    for year in YEARS:
        cutoff = f"{year}-01-01"
        bucket_dfs_year = build_bucket_dataframes(bucket_acc, names_seen, known_pids, reference_columns, cutoff)
        result_year = compute_value_scores(bucket_dfs_year, registry)
        qualified = result_year["value_score"].notna().sum()
        qualifying_counts.append({"year": year, "players_qualified": int(qualified)})
        print(f"  {year}: {qualified} players qualified for a Value Score as of {cutoff}")

        year_prices = auction_df[auction_df["Year"] == year][["player_id", "Player", "Price / Retention (INR Cr)"]]
        year_prices = year_prices[year_prices["player_id"] != ""]
        for _, row in year_prices.iterrows():
            pid = row["player_id"]
            if pid in result_year.index and pd.notna(result_year.loc[pid, "value_score"]):
                calibration_pairs.append({
                    "year": year,
                    "player_id": pid,
                    "player_name": row["Player"],
                    "value_score": result_year.loc[pid, "value_score"],
                    "price_cr": row["Price / Retention (INR Cr)"],
                })

    counts_df = pd.DataFrame(qualifying_counts)
    counts_df.to_csv(DIR / "year_cutoff_qualifying_counts.csv", index=False)
    print("\nSaved year_cutoff_qualifying_counts.csv")
    print(counts_df.to_string(index=False))

    pairs_df = pd.DataFrame(calibration_pairs)
    pairs_df.to_csv(DIR / "year_cutoff_calibration_pairs.csv", index=False)
    correlation = pairs_df["value_score"].corr(pairs_df["price_cr"])
    print(f"\nSaved year_cutoff_calibration_pairs.csv: {len(pairs_df)} contemporaneous (score, real price) pairs")
    print(f"Correlation (value_score vs real price), year-matched: {correlation:.3f}")

    # NOTE: estimated_price_cr was tried and dropped -- tested at correlation
    # ~0.28 against real sale prices even after year-matching and adding more
    # batting/bowling features, which isn't reliable enough to publish as a
    # price. Value Score stays as a relative skill-ranking signal only; real
    # price prediction is Phase 2's job (a trained model, not a hand-built
    # formula). See year_cutoff_calibration_pairs.csv for the raw evidence.
    print("\nWriting player_value_index.csv (value_score only -- no price estimate, see note above)...")
    today_result = compute_value_scores(today_bucket_dfs, registry)

    out_cols = ["player_name", "primary_role", "country", "batting_score", "bowling_score", "keeping_score", "value_score"]
    output = today_result.reset_index()[["player_id"] + out_cols]
    output = output.dropna(subset=["value_score"]).sort_values("value_score", ascending=False)
    output.to_csv(DIR / "player_value_index.csv", index=False)

    print(f"player_value_index.csv rewritten: {len(output)} players")


if __name__ == "__main__":
    main()
