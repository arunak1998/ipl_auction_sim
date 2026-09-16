"""
Joins the IPL_Auction_Retention_Master_2011_2026.xlsx price data to Cricsheet
player_id (from players_registry.csv) so Phase 2 can pull year-appropriate
stats for each auction row without re-doing name resolution.

Matching strategy:
  1. Manual alias table for known Cricsheet naming quirks (reordered initials,
     dropped clan names, compound surnames) -- these can't be inferred
     generically, they were resolved by manual lookup.
  2. Generic surname + given-initials matcher for everything else. Surname is
     the last whitespace-separated token (hyphenated surnames like
     "Fraser-McGurk" are kept intact, not split further). A single-word name
     (e.g. "Sreesanth") matches on surname alone.

Known gaps (documented, not silently hidden):
  - "Jeevan Mendis" has no matching entry in the registry under any spelling
    tried -- left unmatched (player_id blank).
  - "Mujeeb Zadran" maps to registry entry "Mujeeb Ur Rahman", but a second
    registry id "Mujeeb-ur-Rehman" likely represents the same real person
    under a different spelling -- his stats may be split across both ids.

Output: backend/data_pipeline/ipl_auction_master_with_player_id.csv
"""

from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
OUT_DIR = Path(__file__).resolve().parent

ALIASES = {
    "Ajantha Mendis": "BAW Mendis",
    "Albie Morkel": "JA Morkel",
    "Auqib Nabi Dar": "Auqib Nabi",
    "Brad Hogg": "GB Hogg",
    "Dinesh Chandimal": "LD Chandimal",
    "Dinesh Karthik": "KD Karthik",
    "Hanuma Vihari": "GH Vihari",
    "Mahela Jayawardene": "DPMD Jayawardene",
    "Mujeeb Zadran": "Mujeeb Ur Rahman",
    "Prasidh Krishna": "M Prasidh Krishna",
    "Sai Sudharsan": "B Sai Sudharsan",
    "Varun Chakravarthy": "CV Varun",
    "Wanindu Hasaranga": "PWH de Silva",
}

UNRESOLVED = {"Jeevan Mendis"}


def load_registry_index(registry_csv: Path):
    df = pd.read_csv(registry_csv, dtype=str)
    by_name = {}
    by_surname = {}
    for _, row in df.iterrows():
        by_name[row["player_name"]] = row["player_id"]
        parts = row["player_name"].split()
        surname = parts[-1].lower()
        initials = "".join(p[0] for p in parts[:-1]).lower()
        by_surname.setdefault(surname, []).append((initials, row["player_id"], row["player_name"]))
    return by_name, by_surname


def match_player_id(full_name: str, by_name: dict, by_surname: dict) -> tuple[str, str]:
    """Returns (player_id, matched_registry_name), both '' if unresolved."""
    if full_name in ALIASES:
        alias_name = ALIASES[full_name]
        return by_name.get(alias_name, ""), alias_name

    if full_name in UNRESOLVED:
        return "", ""

    parts = full_name.split()
    surname = parts[-1].lower()
    given_initials = "".join(p[0] for p in parts[:-1]).lower()
    candidates = by_surname.get(surname, [])

    if not given_initials:
        # Single-word name (e.g. "Sreesanth") -- match on surname alone if unambiguous.
        if len(candidates) == 1:
            initials, pid, name = candidates[0]
            return pid, name
        return "", ""

    # EXACT initials match only -- no prefix leniency. A prefix rule (e.g.
    # "a".startswith("a") or "ar".startswith("a")) still lets one short
    # initials string collide with several longer ones sharing that first
    # letter -- the same class of bug as the original `reg_initials[0] ==
    # given_initials[0]` fallback, just triggered less often. If more than
    # one candidate has the exact same initials, the name is genuinely
    # ambiguous -- leave it unmatched rather than guessing.
    matches = [
        (pid, name) for reg_initials, pid, name in candidates
        if reg_initials and reg_initials == given_initials
    ]
    return matches[0] if len(matches) == 1 else ("", "")


def main():
    by_name, by_surname = load_registry_index(OUT_DIR / "players_registry.csv")

    df = pd.read_excel(DATA_DIR / "IPL_Auction_Retention_Master_2011_2026_new.xlsx", sheet_name="Master Data (2011-2026)")

    matched = df["Player"].apply(lambda p: match_player_id(str(p), by_name, by_surname))
    df["player_id"] = [m[0] for m in matched]
    df["matched_registry_name"] = [m[1] for m in matched]

    df.to_csv(OUT_DIR / "ipl_auction_master_with_player_id.csv", index=False)

    total = len(df)
    matched_rows = (df["player_id"] != "").sum()
    unique_players = df["Player"].nunique()
    unique_matched = df.loc[df["player_id"] != "", "Player"].nunique()

    print(f"Rows: {matched_rows}/{total} matched ({matched_rows / total * 100:.1f}%)")
    print(f"Unique players: {unique_matched}/{unique_players} matched ({unique_matched / unique_players * 100:.1f}%)")
    unresolved_names = sorted(set(df.loc[df["player_id"] == "", "Player"]))
    if unresolved_names:
        print("Unresolved:", unresolved_names)


if __name__ == "__main__":
    main()
