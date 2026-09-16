"""
Phase 1: rules-based Player Value Score (0-100). This is NOT a trained ML
model -- it's a deterministic percentile scoring formula. It exists as a
fallback ranking for players with no real auction sale-price history, and as
a sanity-check baseline for the Phase 2 trained model to be compared against.

Approach:
  1. Per bucket (IPL / INTL_T20 / OTHER_T20), percentile-rank each player's
     batting and bowling metrics against same-role peers in that bucket.
     A bucket only counts for a player if they clear a minimum-innings floor
     (avoids a 2-game fluke dominating the score).
  1b. That raw percentile is RELATIVE to its own peer group, not an
      absolute quality measure -- a 95th-percentile domestic-league batter
      and a 76th-percentile IPL batter aren't the same thing. Each bucket's
      percentile is scaled down by a fixed ceiling before it's combined
      (IPL 1.0, INTL_T20 0.92, OTHER_T20 0.70, or 0.60 for players whose
      OTHER_T20 record is ONLY a domestic feeder competition like the Syed
      Mushtaq Ali Trophy rather than a major franchise league) -- this is
      what stops an uncapped domestic-only player from ever outscoring an
      established IPL regular. It's then shrunk toward that bucket's
      neutral midpoint by sample-size confidence (n/(n+k)), so clearing the
      innings floor by a little isn't trusted as much as a long track
      record.
  2. Combine each player's per-bucket batting/bowling scores into one
     batting_score and one bowling_score, weighted by bucket (IPL weighted
     highest, as it's most predictive of IPL value) and renormalized across
     whichever buckets a player actually has data in.
  3. Roll into one Value Score per role:
       Batter        -> batting_score
       Bowler        -> bowling_score
       Wicketkeeper  -> batting_score + keeping bonus (from stumpings/catches)
       All-rounder   -> 70/30 blend weighted toward their stronger discipline

NOTE on price prediction: an estimated_price_cr column was tried (calibrating
Value Score against real sale prices in ipl_auction_master_with_player_id.csv)
but was dropped -- see year_cutoff_value_index.py's docstring. Even after
year-matching scores to contemporaneous prices and adding more batting/
bowling features, correlation against real prices stayed ~0.28, too weak to
publish as a price. Value Score is a relative skill ranking only; real price
prediction is Phase 2's job. build_calibration_anchor/apply_calibration_anchor
are kept here as reusable building blocks, not because this file uses them.

Output: player_value_index.csv
  player_id, player_name, role, country,
  ipl_batting_score, ipl_bowling_score, intl_batting_score, intl_bowling_score,
  other_batting_score, other_bowling_score, batting_score, bowling_score,
  value_score
"""

from pathlib import Path

import numpy as np
import pandas as pd

DIR = Path(__file__).resolve().parent

MIN_INNINGS = {"IPL": 20, "INTL_T20": 10, "OTHER_T20": 15}
BUCKET_WEIGHTS = {"IPL": 0.6, "INTL_T20": 0.25, "OTHER_T20": 0.15}
BUCKET_FILES = {
    "IPL": "ipl_stats.csv",
    "INTL_T20": "international_t20_stats.csv",
    "OTHER_T20": "other_t20_stats.csv",
}

BATTING_METRICS_HIGHER_BETTER = ["batting_average", "batting_strike_rate", "recent_average", "recent_strike_rate", "death_strike_rate", "boundary_percentage"]
# Lower is better for these -- percentile is inverted.
BATTING_METRICS_LOWER_BETTER = ["batting_dot_ball_pct"]
BOWLING_METRICS_LOWER_BETTER = ["bowling_average", "economy", "bowling_strike_rate", "boundary_pct_conceded"]
BOWLING_METRICS_HIGHER_BETTER = ["recent_wickets"]

# BUG FIX: "Syed Mushtaq Ali Trophy" -- India's own premier domestic T20
# tournament, the direct feeder competition into IPL selection -- was
# missing here entirely. Since roughly half the auction pool is uncapped
# Indian domestic players whose ONLY OTHER_T20 record is this exact
# competition, the omission meant they were excluded from the OTHER_T20
# ranking pool regardless of how many innings they'd played (discovered by
# instrumenting a single unscored player, Vishnu Solanki: 40 batting
# innings, well over the 15-innings floor, still unscored -- because his
# only competition wasn't on this list, not because of the floor). Also
# added "HRV Cup", the pre-rename name of the same NZ domestic competition
# already whitelisted as "HRV Twenty20", for consistency.
OTHER_T20_TIER2_LEAGUES = {"Syed Mushtaq Ali Trophy"}

OTHER_T20_TIER1_LEAGUES = {
    "Big Bash League", "Pakistan Super League", "Caribbean Premier League",
    "Bangladesh Premier League", "Lanka Premier League", "SA20",
    "Mzansi Super League", "Ram Slam T20 Challenge", "CSA T20 Challenge",
    "MiWAY T20 Challenge", "International League T20", "Major League Cricket",
    "NatWest T20 Blast", "Vitality Blast", "Vitality Blast Men",
    "Super Smash", "HRV Twenty20", "HRV Cup", "The Hundred Men's Competition",
}

# --- percentile-to-value scaling (BUG FIX: percentile is a RELATIVE rank
# within one bucket's peer group, not an absolute quality measure -- a 95th
# percentile SMAT batter and a 76th percentile IPL batter were being
# combined as if directly comparable, which is how uncapped domestic-only
# players (e.g. Ricky Bhui, Tanush Kotian) ended up outscoring Kohli,
# Bumrah, and Rohit Sharma. Each bucket's percentile is capped by how
# strong that competition actually is BEFORE it enters weighted_combine,
# so the best possible SMAT-only score can never reach IPL territory.
# SMAT is split out from the other OTHER_T20 leagues (BBL/PSL/CPL/...) with
# its own, lower ceiling: it's a domestic feeder competition with weaker
# bowling attacks than the major franchise leages, so inflates rate stats
# even within OTHER_T20's own peer group. ---
IPL_CEILING = 1.0
INTL_T20_CEILING = 0.92
OTHER_T20_TIER1_CEILING = 0.70
OTHER_T20_TIER2_CEILING = 0.60
# FRINGE: everyone left with a real record after FRANCHISE and SMAT have
# both had first claim on them -- weaker domestic/club T20s (Ireland's
# inter-provincial trophy, minor European/Nepal leagues, etc). Below SMAT
# because these competitions are a further step down in bowling quality,
# but still a REAL, differentiated score rather than the flat uncapped
# default -- a genuine standout in a weak league should still separate
# from a total unknown with zero data.
OTHER_T20_FRINGE_CEILING = 0.40
# Associate-nation internationals: a real international record, but not
# against Full Member bowling attacks -- above domestic fringe cricket
# (it's still international cricket) but well below the Full Member ceiling.
INTL_T20_ASSOCIATE_CEILING = 0.45

# --- shrinkage: pulls a thin sample toward "average for this bucket and
# ceiling" rather than trusting its raw percentile at full strength. Applied
# here, at the bucket level, rather than on the raw rate stats beforehand --
# same empirical-Bayes idea (n / (n+k) confidence), scoped to where the
# percentile actually gets consumed. k is on the same order as each
# bucket's MIN_INNINGS floor, so a player just past the floor still gets
# pulled heavily toward the neutral midpoint, and confidence climbs toward
# 1 only with real volume. ---
SHRINKAGE_K = {"IPL": 15, "INTL_T20": 8, "OTHER_T20": 10}

# FRINGE tiers only: a much lower innings floor than the credible-peer-group
# tiers above them (still >=5 peers required to rank against at all).
# Shrinkage carries the fluke risk here, not the floor -- a player just
# past this bar gets pulled hard toward the tier's neutral midpoint by
# SHRINKAGE_K, landing in a narrow band near the bottom rather than at a
# raw (and meaningless, on 3-4 innings) percentile extreme.
FRINGE_MIN_INNINGS = 3


def _played_in(row: pd.Series, column: str, target_set: set) -> bool:
    val = row[column]
    if not isinstance(val, str) or not val:
        return False
    return any(x.strip() in target_set for x in val.split(","))


# Declarative, ordered (highest first) per-bucket tier list -- adding a
# competition to a tier, or adding a whole new tier, is now a data change
# here, not a special case threaded through compute_bucket_scores. Each
# tier is {name, ceiling (float, or None if ceiling_fn decides per row),
# ceiling_fn, membership (row -> bool, or None to mean "everyone left")}.
# compute_bucket_scores resolves a player to the FIRST tier (in this order)
# whose membership they satisfy, from whatever's left after higher tiers
# have already claimed their rows -- a player is scored in exactly one
# tier per bucket, never blended across tiers or dragged down by a lower
# one they also happen to qualify for.
BUCKET_TIERS = {
    "IPL": [
        {"name": "IPL", "ceiling": IPL_CEILING, "ceiling_fn": None, "membership": None},
    ],
    "INTL_T20": [
        {
            "name": "FULL_MEMBER", "ceiling": INTL_T20_CEILING, "ceiling_fn": None,
            "membership": lambda row: _played_in(row, "teams_played_for", FULL_MEMBER_NATIONS),
        },
        # FRINGE, reached only by players FULL_MEMBER didn't already claim:
        # associate-nation internationals, previously excluded entirely.
        {
            "name": "ASSOCIATE_FRINGE", "ceiling": INTL_T20_ASSOCIATE_CEILING, "ceiling_fn": None,
            "membership": None, "min_innings": FRINGE_MIN_INNINGS, "is_fringe": True,
        },
    ],
    "OTHER_T20": [
        # FRANCHISE and SMAT are now genuinely separate peer groups (each
        # gets its OWN percentile ranking), not a shared pool with the
        # ceiling picked after the fact -- a top SMAT batter's percentile
        # should be computed among SMAT peers, not diluted by mixing with
        # BBL/PSL players in the same ranking. Order matters: FRANCHISE is
        # tried first, so a player who qualifies for it is never also
        # evaluated (and potentially dragged down) by the SMAT-only pool.
        {
            "name": "FRANCHISE", "ceiling": OTHER_T20_TIER1_CEILING, "ceiling_fn": None,
            "membership": lambda row: _played_in(row, "competitions_played", OTHER_T20_TIER1_LEAGUES),
        },
        {
            "name": "SMAT", "ceiling": OTHER_T20_TIER2_CEILING, "ceiling_fn": None,
            "membership": lambda row: _played_in(row, "competitions_played", OTHER_T20_TIER2_LEAGUES),
        },
        # FRINGE, reached only by players neither tier above claimed:
        # weaker domestic/club T20s, previously excluded entirely.
        {
            "name": "FRINGE", "ceiling": OTHER_T20_FRINGE_CEILING, "ceiling_fn": None,
            "membership": None, "min_innings": FRINGE_MIN_INNINGS, "is_fringe": True,
        },
    ],
}


def scale_and_shrink(raw_percentile: pd.Series, ceiling: pd.Series, innings: pd.Series, k: float) -> pd.Series:
    """percentile (0-100, relative to peers) -> ceiling-scaled, then
    shrunk toward the neutral midpoint (50th percentile at that ceiling)
    by sample-size confidence n/(n+k)."""
    scaled = raw_percentile * ceiling
    confidence = innings / (innings + k)
    neutral = 50.0 * ceiling
    return confidence * scaled + (1 - confidence) * neutral

FULL_MEMBER_NATIONS = {
    "India", "Australia", "England", "South Africa", "New Zealand", "Pakistan",
    "Sri Lanka", "Bangladesh", "West Indies", "Afghanistan", "Ireland", "Zimbabwe",
}

ALL_ROUNDER_STRONG_WEIGHT = 0.7
ALL_ROUNDER_WEAK_WEIGHT = 0.3
WICKETKEEPER_KEEPING_WEIGHT = 0.2
WICKETKEEPER_BATTING_WEIGHT = 0.8


def percentile_score(df: pd.DataFrame, columns: list[str], higher_is_better: bool) -> pd.Series:
    """Average percentile rank (0-100) across the given columns, computed
    within the rows of df (already filtered to one role+bucket)."""
    ranks = pd.DataFrame(index=df.index)
    for col in columns:
        pct = df[col].rank(pct=True, ascending=higher_is_better)
        ranks[col] = pct * 100
    return ranks.mean(axis=1)


def combined_percentile_score(df: pd.DataFrame, higher_metrics: list[str], lower_metrics: list[str]) -> pd.Series:
    """Percentile score across a mix of higher-is-better and lower-is-better metrics."""
    parts = []
    if higher_metrics:
        parts.append((percentile_score(df, higher_metrics, higher_is_better=True), len(higher_metrics)))
    if lower_metrics:
        parts.append((percentile_score(df, lower_metrics, higher_is_better=False), len(lower_metrics)))
    total_weight = sum(w for _, w in parts)
    return sum(s * w for s, w in parts) / total_weight


def compute_bucket_scores(bucket_name: str, bucket_df: pd.DataFrame, registry: pd.DataFrame) -> pd.DataFrame:
    df = bucket_df.merge(registry[["player_id", "primary_role"]], on="player_id", how="left")

    df["batting_score"] = np.nan
    df["bowling_score"] = np.nan
    df["batting_is_fringe"] = False
    df["bowling_is_fringe"] = False
    df["batting_tier"] = None
    df["bowling_tier"] = None

    k = SHRINKAGE_K[bucket_name]

    # Guard against a pandas quirk: boolean-filtering a 0-row DataFrame via
    # .apply() can silently drop all columns. A bucket can legitimately be
    # empty for an early year-cutoff snapshot (e.g. OTHER_T20 leagues like
    # BBL/PSL didn't exist yet in 2011) -- nothing to filter in that case.
    remaining = df
    for tier in BUCKET_TIERS[bucket_name]:
        if remaining.empty:
            break
        if tier["membership"] is None:
            in_tier = remaining
        else:
            in_tier = remaining[remaining.apply(tier["membership"], axis=1)]
        if in_tier.empty:
            continue

        # Each tier can override the bucket's default innings floor (only
        # FRINGE tiers do, much lower -- see FRINGE_MIN_INNINGS). The >=5
        # peer-group-size check still applies regardless, so a lower floor
        # never means ranking against a near-empty pool.
        min_innings = tier.get("min_innings", MIN_INNINGS[bucket_name])
        is_fringe = tier.get("is_fringe", False)

        for role, group in in_tier.groupby("primary_role"):
            bat_eligible = group[group["innings_batted"] >= min_innings]
            if len(bat_eligible) >= 5:  # need a minimum peer group to rank against
                raw_pct = combined_percentile_score(bat_eligible, BATTING_METRICS_HIGHER_BETTER, BATTING_METRICS_LOWER_BETTER)
                ceiling = tier["ceiling"] if tier["ceiling"] is not None else bat_eligible.apply(tier["ceiling_fn"], axis=1)
                scores = scale_and_shrink(raw_pct, ceiling, bat_eligible["innings_batted"], k)
                df.loc[scores.index, "batting_score"] = scores
                df.loc[scores.index, "batting_is_fringe"] = is_fringe
                df.loc[scores.index, "batting_tier"] = f"{bucket_name}/{tier['name']}"

            bowl_eligible = group[group["innings_bowled"] >= min_innings]
            if len(bowl_eligible) >= 5:
                raw_pct = combined_percentile_score(bowl_eligible, BOWLING_METRICS_HIGHER_BETTER, BOWLING_METRICS_LOWER_BETTER)
                ceiling = tier["ceiling"] if tier["ceiling"] is not None else bowl_eligible.apply(tier["ceiling_fn"], axis=1)
                scores = scale_and_shrink(raw_pct, ceiling, bowl_eligible["innings_bowled"], k)
                df.loc[scores.index, "bowling_score"] = scores
                df.loc[scores.index, "bowling_is_fringe"] = is_fringe
                df.loc[scores.index, "bowling_tier"] = f"{bucket_name}/{tier['name']}"

            if role == "Wicketkeeper":
                keeping_raw = group["stumpings"] + group["catches"]
                keeping_pct = keeping_raw.rank(pct=True) * 100
                df.loc[keeping_pct.index, "keeping_score"] = keeping_pct

        # Only drop rows that actually GOT a score here, not everyone who
        # merely matched this tier's membership test. A player who played
        # SMAT but has too few innings to clear even SMAT's own floor
        # would otherwise be claimed by SMAT's membership check and never
        # reach FRINGE at all -- membership says "which competition did
        # they play," not "were they scored here."
        resolved = df.loc[in_tier.index, ["batting_score", "bowling_score"]].notna().any(axis=1)
        remaining = remaining.drop(in_tier.index[resolved])

    return df[
        [
            "player_id", "batting_score", "bowling_score", "batting_is_fringe", "bowling_is_fringe",
            "batting_tier", "bowling_tier",
        ]
        + (["keeping_score"] if "keeping_score" in df else [])
    ]


def weighted_combine(row_scores: dict[str, float]) -> float | None:
    """Weighted average over buckets where the player has a non-null score,
    renormalizing weights across whatever buckets are actually available."""
    available = {b: s for b, s in row_scores.items() if pd.notna(s)}
    if not available:
        return np.nan
    total_weight = sum(BUCKET_WEIGHTS[b] for b in available)
    return sum(s * BUCKET_WEIGHTS[b] for b, s in available.items()) / total_weight


def combine_discipline(row: pd.Series, discipline: str) -> float | None:
    """Same weighted_combine, but a FRINGE-tier bucket score is only used
    when it's the ONLY thing available for this discipline. Without this,
    a player with a strong, credible score (e.g. a real IPL batting
    average) could get diluted by a barely-qualifying FRINGE score from an
    unrelated weak league -- a real player (B Sai Sudharsan) dropped from
    79.8 to 68.5 this way when the FRINGE floor was first lowered, purely
    from picking up a 3-innings score nobody should trust over his real
    IPL record. Fringe is a last resort, never a diluter of something
    better."""
    scores = {b: row[f"{b.lower()}_{discipline}_score"] for b in BUCKET_WEIGHTS}
    is_fringe = {b: row[f"{b.lower()}_{discipline}_is_fringe"] for b in BUCKET_WEIGHTS}
    credible = {b: s for b, s in scores.items() if pd.notna(s) and not is_fringe[b]}
    if credible:
        return weighted_combine(credible)
    return weighted_combine(scores)


def compute_value_scores(bucket_dfs: dict[str, pd.DataFrame], registry: pd.DataFrame) -> pd.DataFrame:
    """Core Phase 1 scoring, decoupled from file I/O so it can be reused for
    a year-cutoff snapshot as well as the full-career run. bucket_dfs must
    have the same columns as ipl_stats.csv / international_t20_stats.csv /
    other_t20_stats.csv (keyed "IPL" / "INTL_T20" / "OTHER_T20").
    Returns a DataFrame indexed by player_id with all intermediate scores
    plus the final value_score (NaN where a player couldn't be scored)."""
    bucket_scores = {b: compute_bucket_scores(b, bucket_dfs[b], registry) for b in BUCKET_WEIGHTS}

    result = registry.set_index("player_id").copy()
    for b, df in bucket_scores.items():
        df = df.set_index("player_id")
        result[f"{b.lower()}_batting_score"] = df["batting_score"]
        result[f"{b.lower()}_batting_is_fringe"] = df["batting_is_fringe"]
        result[f"{b.lower()}_batting_tier"] = df["batting_tier"]
        result[f"{b.lower()}_bowling_score"] = df["bowling_score"]
        result[f"{b.lower()}_bowling_is_fringe"] = df["bowling_is_fringe"]
        result[f"{b.lower()}_bowling_tier"] = df["bowling_tier"]
        if "keeping_score" in df:
            result[f"{b.lower()}_keeping_score"] = df["keeping_score"]

    result["batting_score"] = result.apply(lambda r: combine_discipline(r, "batting"), axis=1)
    result["bowling_score"] = result.apply(lambda r: combine_discipline(r, "bowling"), axis=1)
    keeping_cols = [c for c in result.columns if c.endswith("_keeping_score")]
    result["keeping_score"] = result[keeping_cols].mean(axis=1) if keeping_cols else np.nan

    def final_value_score(row) -> float | None:
        role = row["primary_role"]
        bat, bowl, keep = row["batting_score"], row["bowling_score"], row["keeping_score"]
        if role == "Batter":
            return bat
        if role == "Bowler":
            return bowl
        if role == "Wicketkeeper":
            if pd.isna(bat):
                return np.nan
            keep_component = keep if pd.notna(keep) else 0
            return WICKETKEEPER_BATTING_WEIGHT * bat + WICKETKEEPER_KEEPING_WEIGHT * keep_component
        if role == "All-rounder":
            if pd.isna(bat) and pd.isna(bowl):
                return np.nan
            if pd.isna(bat):
                return bowl
            if pd.isna(bowl):
                return bat
            strong, weak = (bat, bowl) if bat >= bowl else (bowl, bat)
            return ALL_ROUNDER_STRONG_WEIGHT * strong + ALL_ROUNDER_WEAK_WEIGHT * weak
        return np.nan

    result["value_score"] = result.apply(final_value_score, axis=1).round(1)
    result["value_score_tier"] = result.apply(value_score_tier, axis=1)
    return result


def dominant_tier(row: pd.Series, discipline: str) -> str | None:
    """Which bucket's tier actually drove combine_discipline's result for
    this discipline -- the single highest-weight bucket among whichever
    set (credible, or fringe-only as a last resort) combine_discipline
    used. A price model consumes this as a categorical feature: a 70
    earned in IPL should carry a different price implication than a 70
    earned in FRINGE, even though value_score alone can't tell them apart."""
    scores = {b: row[f"{b.lower()}_{discipline}_score"] for b in BUCKET_WEIGHTS}
    is_fringe = {b: row[f"{b.lower()}_{discipline}_is_fringe"] for b in BUCKET_WEIGHTS}
    tiers = {b: row[f"{b.lower()}_{discipline}_tier"] for b in BUCKET_WEIGHTS}
    credible = {b: s for b, s in scores.items() if pd.notna(s) and not is_fringe[b]}
    pool = credible if credible else {b: s for b, s in scores.items() if pd.notna(s)}
    if not pool:
        return None
    dominant_bucket = max(pool, key=lambda b: BUCKET_WEIGHTS[b])
    return tiers[dominant_bucket]


def value_score_tier(row: pd.Series) -> str | None:
    """The tier label behind final_value_score's chosen discipline for
    this player's role -- mirrors final_value_score's own role dispatch
    (including the all-rounder strong/weak selection) so the label always
    names the tier that actually produced the number."""
    role = row["primary_role"]
    if role in ("Batter", "Wicketkeeper"):
        return dominant_tier(row, "batting")
    if role == "Bowler":
        return dominant_tier(row, "bowling")
    if role == "All-rounder":
        bat, bowl = row["batting_score"], row["bowling_score"]
        if pd.isna(bat) and pd.isna(bowl):
            return None
        if pd.isna(bat):
            return dominant_tier(row, "bowling")
        if pd.isna(bowl):
            return dominant_tier(row, "batting")
        return dominant_tier(row, "batting") if bat >= bowl else dominant_tier(row, "bowling")
    return None


def build_calibration_anchor(pairs_df: pd.DataFrame) -> pd.DataFrame:
    """Takes a DataFrame with 'value_score' and 'price_cr' columns (each row
    one real sale matched to a score computed AS OF that same point in time)
    and collapses it to a decile-median (score -> price) anchor curve."""
    pairs_df = pairs_df.dropna(subset=["value_score", "price_cr"]).sort_values("value_score")
    pairs_df["decile"] = pd.qcut(pairs_df["value_score"], q=10, duplicates="drop")
    anchor = pairs_df.groupby("decile", observed=True).agg(
        score=("value_score", "median"), price=("price_cr", "median")
    ).reset_index(drop=True)
    return anchor.sort_values("score")


def apply_calibration_anchor(value_scores: pd.Series, anchor: pd.DataFrame) -> pd.Series:
    """Interpolates an estimated price for each value_score against the anchor curve."""
    return pd.Series(
        np.interp(value_scores, anchor["score"], anchor["price"], left=anchor["price"].iloc[0], right=anchor["price"].iloc[-1]),
        index=value_scores.index,
    )


def calibrate_price(value_scores: pd.Series, auction_df: pd.DataFrame, registry: pd.DataFrame) -> pd.Series:
    """Naive calibration: matches today's value_score against ALL historical
    sale prices regardless of year (each player's score is compared against
    prices from years when their career looked very different). Kept only as
    a quick fallback -- year_cutoff_value_index.py's year-matched calibration
    is the correct approach and supersedes this for the real pipeline."""
    priced = auction_df[auction_df["player_id"] != ""][["player_id", "Price / Retention (INR Cr)"]].copy()
    priced = priced.rename(columns={"Price / Retention (INR Cr)": "price_cr"})
    priced = priced.merge(value_scores.rename("value_score"), left_on="player_id", right_index=True)

    anchor = build_calibration_anchor(priced)
    return apply_calibration_anchor(value_scores, anchor)


def main():
    registry = pd.read_csv(DIR / "players_registry.csv", dtype={"player_id": str})
    bucket_dfs = {b: pd.read_csv(DIR / f, dtype={"player_id": str}) for b, f in BUCKET_FILES.items()}

    result = compute_value_scores(bucket_dfs, registry)

    out_cols = (
        ["player_name", "primary_role", "country"]
        + [f"{b.lower()}_batting_score" for b in BUCKET_WEIGHTS]
        + [f"{b.lower()}_bowling_score" for b in BUCKET_WEIGHTS]
        + ["batting_score", "bowling_score", "keeping_score", "value_score", "value_score_tier"]
    )
    output = result.reset_index()[["player_id"] + out_cols]
    output = output.dropna(subset=["value_score"])
    output = output.sort_values("value_score", ascending=False)
    output.to_csv(DIR / "player_value_index.csv", index=False)

    print(f"Scored {len(output)} of {len(result)} players (rest had insufficient data in every bucket).")
    print(output.head(15).to_string(index=False))


if __name__ == "__main__":
    main()
