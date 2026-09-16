"""
Loads the live auction pool and the ten franchise profiles.

JOIN RULE (non-negotiable): value scores are joined on player_id, never on
names. A previous version carried a surname+initials name matcher whose
"first initial matches" fallback silently collapsed distinct players
(Rohit Sharma vs Rituraj Sharma), which poisoned value scores and every
downstream price. player_id_map_final.csv is the one-time, human-reviewed
auction_name -> registry player_id map; this module does an exact dict
lookup against it and nothing else. There is no fuzzy matcher in this file
and none should ever be added.

TWO DIFFERENT IDS, deliberately:
  - AuctionPlayer.player_id  -- "retained-{row}", this pool's own id, keyed
    positionally off the CSV. fair_prices.json is keyed by THIS id, so row
    order here is load-bearing: never sort or filter the CSV before
    assigning ids.
  - the registry id (e.g. "d290c5b5") -- Cricsheet's id, used only to look
    up value_score, and never exposed outside this module.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
PIPELINE_DIR = Path(__file__).resolve().parents[1] / "data_pipeline"

POOL_CSV = DATA_DIR / "IPL_2025_Retained_Players_Detailed.csv"
ID_MAP_CSV = PIPELINE_DIR / "player_id_map_final.csv"
VALUE_INDEX_CSV = PIPELINE_DIR / "player_value_index.csv"
TEAM_PROFILES_JSON = PIPELINE_DIR / "team_profiles.json"

# The CSV writes roles in caps; squad_rules.py and team_profiles.json both
# speak title case, so normalise once here at the boundary.
ROLE_NORMALISATION = {
    "BATTER": "Batter",
    "BOWLER": "Bowler",
    "ALL-ROUNDER": "All-rounder",
    "WICKETKEEPER": "Wicketkeeper",
}

# No measured career record -> a flat prior by status, flagged via
# value_score_is_real so nothing downstream mistakes it for a real number.
DEFAULT_VALUE_SCORE_CAPPED = 40.0
DEFAULT_VALUE_SCORE_UNCAPPED = 20.0


@dataclass
class AuctionPlayer:
    player_id: str          # pool id ("retained-N") -- fair_prices.json key
    name: str
    role: str               # Batter | Bowler | All-rounder | Wicketkeeper
    country: str
    is_overseas: bool
    capped: bool
    base_price_cr: float
    value_score: float
    value_score_is_real: bool
    set_name: str
    bowler_subtype: str | None   # "Pace" | "Spin" | None


def _classify_bowler_subtype(bowling_style: str) -> str | None:
    """Spin is checked FIRST on purpose: 'RIGHT ARM Medium Off Spin' contains
    both keywords and is a spinner. 'Unorthodox' contains 'ORTHODOX' as a
    substring, so both left-arm slow variants land in Spin correctly."""
    style = (bowling_style or "").strip().upper()
    if not style:
        return None
    if "SPIN" in style or "ORTHODOX" in style:
        return "Spin"
    if "FAST" in style or "MEDIUM" in style:
        return "Pace"
    return None


def _load_value_score_by_registry_id() -> dict[str, float]:
    scores: dict[str, float] = {}
    with open(VALUE_INDEX_CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = row.get("value_score", "")
            if raw not in ("", None):
                scores[row["player_id"]] = float(raw)
    return scores


def _load_registry_id_by_auction_name() -> dict[str, str]:
    mapping: dict[str, str] = {}
    with open(ID_MAP_CSV, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = (row.get("player_id") or "").strip()
            if pid:
                mapping[row["auction_name"].strip()] = pid
    return mapping


def load_player_pool() -> list[AuctionPlayer]:
    registry_id_by_name = _load_registry_id_by_auction_name()
    value_score_by_registry_id = _load_value_score_by_registry_id()

    players: list[AuctionPlayer] = []
    with open(POOL_CSV, newline="", encoding="utf-8") as fh:
        for idx, row in enumerate(csv.DictReader(fh)):
            name = row["Full Name"].strip()
            country = row["Country"].strip()
            capped = row["Capped/Uncapped"].strip() == "Capped"

            registry_id = registry_id_by_name.get(name)
            measured = value_score_by_registry_id.get(registry_id) if registry_id else None
            if measured is not None:
                value_score, is_real = measured, True
            else:
                value_score = DEFAULT_VALUE_SCORE_CAPPED if capped else DEFAULT_VALUE_SCORE_UNCAPPED
                is_real = False

            players.append(
                AuctionPlayer(
                    player_id=f"retained-{idx}",
                    name=name,
                    role=ROLE_NORMALISATION[row["Role"].strip().upper()],
                    country=country,
                    is_overseas=country != "India",
                    capped=capped,
                    # CSV carries base price in lakhs; the whole codebase is Crore.
                    base_price_cr=float(row["Base-Price"]) / 100.0,
                    value_score=value_score,
                    value_score_is_real=is_real,
                    set_name=row["Set"].strip(),
                    bowler_subtype=_classify_bowler_subtype(row["Bowling Style"]),
                )
            )
    return players


def load_team_history_features() -> dict[str, dict]:
    """The other team-level data source, data/team_history_features.json --
    NOT merged into team_profiles.json. Real per-team historical spend
    patterns (star_spend_bowler_pct etc.), used by the star_spend
    observation variant (rl/auction_mdp.py's team_variant="star_spend")."""
    path = DATA_DIR / "team_history_features.json"
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_team_profiles() -> list[dict]:
    with open(TEAM_PROFILES_JSON, encoding="utf-8") as fh:
        return json.load(fh)
