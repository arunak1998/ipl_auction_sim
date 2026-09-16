"""
Builds a data-driven behavioral profile for each of the 10 current IPL
franchises, from their real auction purchase history -- replacing the
hand-picked AIStrategy weights in the frontend's defaultTeams.ts with
numbers derived from what these franchises have actually done.

Team identity: exact "Team (current name)" match only. Straight renames are
already merged by the source data (Kings XI Punjab -> Punjab Kings, Delhi
Daredevils -> Delhi Capitals, Royal Challengers Bangalore -> Royal
Challengers Bengaluru all collapse to one current-name value). Deccan
Chargers is tagged "Sunrisers Hyderabad (lineage)" by the source -- a
softer distinction the data itself makes, not a straight rename -- so it
is deliberately kept OUT of Sunrisers Hyderabad's profile rather than
merged in. Defunct/temporary franchises with no current-day team (Pune
Warriors India, Rising Pune Supergiant, the 2016-17 Gujarat Lions, Kochi
Tuskers Kerala) are excluded entirely.

Uses IPL_Auction_Retention_Master_2011_2026_new.xlsx, which (unlike the
original file) correctly labels each row's Type as Auction / Retained /
Draft instead of mislabeling everything "Auction". This matters:
Retained prices follow BCCI's fixed retention-slab rules, not competitive
bidding, so mixing them into "team aggression" behavioral stats would be
misleading -- a team paying a preset retention fee isn't the same signal
as winning a bidding war. So:
  - Behavioral profile (role spend, aggression multiplier, marquee
    affinity, overseas preference) is computed from Type=="Auction" rows
    only.
  - current_squad is built separately, from ALL transaction types in each
    team's most recent recorded year -- this is now possible because
    Retained rows exist in this file (they didn't in the original).
    Caveat, stated plainly: this reflects players with a recorded
    transaction in that specific year, which may still be incomplete for
    a mini-auction year where an already-retained-in-a-prior-year player
    had no new transaction to record.

Team identity: exact "Team (current name)" match only. Straight renames are
already merged by the source data (Kings XI Punjab -> Punjab Kings, Delhi
Daredevils -> Delhi Capitals, Royal Challengers Bangalore -> Royal
Challengers Bengaluru all collapse to one current-name value). Deccan
Chargers is tagged "Sunrisers Hyderabad (lineage)" by the source -- a
softer distinction the data itself makes, not a straight rename -- so it
is deliberately kept OUT of Sunrisers Hyderabad's profile rather than
merged in. Defunct/temporary franchises with no current-day team (Pune
Warriors India, Rising Pune Supergiant, the 2016-17 Gujarat Lions, Kochi
Tuskers Kerala) are excluded entirely.

Budget: fixed at 125 Cr for all teams (the 2026 real salary cap, per
FX & Purse Reference / user decision), not derived per-team.

Output: team_profiles.json
"""

import json
from pathlib import Path

import pandas as pd

from rl.data_loader import build_bowler_subtype_name_matcher

DIR = Path(__file__).resolve().parent
BUDGET_CR = 125.0

# Verified from the data itself: these years show a large row-count spike
# (63-126 transactions) vs. 15-36 in other years, matching real IPL mega-
# auction history (full roster resets), as opposed to small annual top-up
# mini-auctions.
MEGA_AUCTION_YEARS = {2011, 2014, 2018, 2022, 2025}

CURRENT_TEAMS = [
    "Chennai Super Kings", "Mumbai Indians", "Royal Challengers Bengaluru",
    "Kolkata Knight Riders", "Sunrisers Hyderabad", "Rajasthan Royals",
    "Delhi Capitals", "Punjab Kings", "Gujarat Titans", "Lucknow Super Giants",
]

TEAM_IDS = {
    "Chennai Super Kings": "csk", "Mumbai Indians": "mi",
    "Royal Challengers Bengaluru": "rcb", "Kolkata Knight Riders": "kkr",
    "Sunrisers Hyderabad": "srh", "Rajasthan Royals": "rr",
    "Delhi Capitals": "dc", "Punjab Kings": "pbks",
    "Gujarat Titans": "gt", "Lucknow Super Giants": "lsg",
}


def main():
    auction_df = pd.read_csv(DIR / "ipl_auction_master_with_player_id.csv", dtype={"player_id": str})
    registry = pd.read_csv(DIR / "players_registry.csv", dtype={"player_id": str})
    country_by_pid = registry.set_index("player_id")["country"].to_dict()

    def origin(pid):
        c = country_by_pid.get(pid, "")
        if not isinstance(c, str) or not c:
            return "Unknown"
        return "Indian" if c == "India" else "Overseas"

    # This historical file has no bowling-style column at all -- only
    # Batter/Bowler/All-Rounder/Wicketkeeper -- so a team's real historical
    # PACE vs SPIN preference can't be computed with the same rigor as the
    # role split above. Best-effort fix: match each historical bowling
    # transaction's player name against the CURRENT auction pool's real
    # bowling-style data (many current players also appear in recent
    # history) and compute the pace/spin split of whatever fraction of
    # historical bowling spend that matches. Coverage is recorded honestly
    # in data_confidence rather than presented as equivalent to the
    # role_spend_distribution_pct's full-coverage real data.
    match_bowler_subtype = build_bowler_subtype_name_matcher()

    profiles = []
    for team in CURRENT_TEAMS:
        all_team_df = auction_df[auction_df["Team (current name)"] == team].copy()
        team_df = all_team_df[all_team_df["Type"] == "Auction"].copy()  # behavioral stats: market bidding only

        years = sorted(int(y) for y in all_team_df["Year"].unique())
        total_spend = team_df["Price / Retention (INR Cr)"].sum()

        role_spend = team_df.groupby("Role")["Price / Retention (INR Cr)"].sum()
        role_spend_pct = {k: float(round(v, 1)) for k, v in (role_spend / total_spend * 100).to_dict().items()} if total_spend else {}

        team_df["origin"] = team_df["player_id"].apply(origin)
        origin_counts = team_df["origin"].value_counts()
        known_origin_total = origin_counts.get("Indian", 0) + origin_counts.get("Overseas", 0)
        overseas_pct = float(round(origin_counts.get("Overseas", 0) / known_origin_total * 100, 1)) if known_origin_total else None

        top5_spend = team_df.nlargest(5, "Price / Retention (INR Cr)")["Price / Retention (INR Cr)"].sum()
        marquee_affinity_pct = float(round(top5_spend / total_spend * 100, 1)) if total_spend else None

        # Pace/spin split -- only bowling-relevant transactions (Bowler,
        # All-Rounder) carry a subtype at all; batters/keepers are excluded
        # from both the numerator and the coverage denominator since "did we
        # match their bowling style" is meaningless for a specialist batter.
        bowling_df = team_df[team_df["Role"].isin(["Bowler", "All-Rounder"])].copy()
        bowling_df["subtype"] = bowling_df["Player"].apply(match_bowler_subtype)
        matched_bowling_spend = bowling_df.loc[bowling_df["subtype"].notna(), "Price / Retention (INR Cr)"].sum()
        total_bowling_spend = bowling_df["Price / Retention (INR Cr)"].sum()
        pace_spin_coverage_pct = (
            float(round(matched_bowling_spend / total_bowling_spend * 100, 1)) if total_bowling_spend else 0.0
        )
        if matched_bowling_spend:
            subtype_spend = bowling_df.groupby("subtype")["Price / Retention (INR Cr)"].sum()
            pace_spin_spend_pct = {
                k: float(round(v, 1)) for k, v in (subtype_spend / matched_bowling_spend * 100).to_dict().items()
            }
        else:
            pace_spin_spend_pct = {}

        latest_year = max(years)
        # Squad = most recent mega-auction (full roster reset) + any mini-
        # auction top-ups since, not just whatever the single latest year
        # happens to contain -- a team untouched by a small 2026 mini-auction
        # is still fielding its full 2025 mega-auction squad, not an empty one.
        mega_years_available = [y for y in years if y in MEGA_AUCTION_YEARS]
        base_year = max(mega_years_available) if mega_years_available else min(years)
        squad_years = [y for y in years if y >= base_year]
        squad_df = all_team_df[all_team_df["Year"].isin(squad_years)]
        # A player could in principle appear in both the mega year and a
        # later mini-auction (e.g. released then re-picked) -- keep only
        # their most recent transaction in that case.
        squad_df = squad_df.sort_values("Year").drop_duplicates(subset="player_id", keep="last")

        current_squad = [
            {
                "player_name": r["Player"],
                "role": r["Role"],
                "type": r["Type"],
                "year_acquired": int(r["Year"]),
                "price_cr": float(r["Price / Retention (INR Cr)"]),
            }
            for _, r in squad_df.sort_values("Price / Retention (INR Cr)", ascending=False).iterrows()
        ]
        squad_spend = squad_df["Price / Retention (INR Cr)"].sum()
        retained_spend = squad_df.loc[squad_df["Type"] == "Retained", "Price / Retention (INR Cr)"].sum()

        profiles.append({
            "team_id": TEAM_IDS[team],
            "team_name": team,
            "budget_cr": BUDGET_CR,
            "data_confidence": {
                "years_active_in_data": years,
                "auction_records_used_for_behavior": len(team_df),
                "note": "Fewer years/records (e.g. Gujarat Titans, Lucknow Super Giants, both 2022+) means a less statistically reliable behavioral profile.",
                "pace_spin_coverage_pct": pace_spin_coverage_pct,
                "pace_spin_note": (
                    "pace_spin_spend_pct is lower-confidence than role_spend_distribution_pct: the "
                    "historical file has no bowling-style column, so this is a best-effort match against "
                    "the CURRENT auction pool's real style data by player name, covering only "
                    f"{pace_spin_coverage_pct}% of this team's historical bowling spend."
                ),
            },
            "role_spend_distribution_pct": role_spend_pct,
            "pace_spin_spend_pct": pace_spin_spend_pct,
            "overseas_spend_pct": overseas_pct,
            "avg_price_to_base_multiplier": float(round(team_df["Price-to-Base Multiplier (x)"].mean(), 2)) if len(team_df) else None,
            "avg_price_paid_cr": float(round(team_df["Price / Retention (INR Cr)"].mean(), 2)) if len(team_df) else None,
            "marquee_affinity_pct": marquee_affinity_pct,
            "current_squad": {
                "as_of_year": int(latest_year),
                "built_from_mega_auction_year": int(base_year),
                "caveat": "Players from the most recent mega-auction year plus any mini-auction transactions since, deduplicated to each player's latest transaction. May still miss an already-retained player who had zero transactions recorded across this whole window.",
                "players": current_squad,
                "player_count": len(current_squad),
                "total_spend_cr": float(round(squad_spend, 2)),
                "retained_spend_cr": float(round(retained_spend, 2)),
            },
        })

    with open(DIR / "team_profiles.json", "w") as fh:
        json.dump(profiles, fh, indent=2)

    print(f"Saved team_profiles.json: {len(profiles)} teams")
    for p in profiles:
        cs = p["current_squad"]
        print(f"  {p['team_name']}: {p['data_confidence']['auction_records_used_for_behavior']} auction records "
              f"({p['data_confidence']['years_active_in_data'][0]}-{p['data_confidence']['years_active_in_data'][-1]}), "
              f"avg multiplier {p['avg_price_to_base_multiplier']}x | "
              f"squad as of {cs['as_of_year']}: {cs['player_count']} players, {cs['total_spend_cr']} Cr "
              f"({cs['retained_spend_cr']} Cr retained)")


if __name__ == "__main__":
    main()
