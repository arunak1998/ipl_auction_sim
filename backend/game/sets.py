"""
Ports src/App.tsx's getUniqueSets() sorting logic exactly, so the backend's
set order matches what the frontend has always shown: Marquee sets first (by
round number), then other sets by round number, then by role-category
priority within a round.
"""

from __future__ import annotations

import re

from rl.data_loader import AuctionPlayer

_CATEGORY_PRIORITY_PREFIXES = [
    (1, ("BA", "BAT")),
    (2, ("AL", "AR")),  # or contains "ROUNDER"
    (3, ("WK", "WIC")),  # or contains "KEEPER"
    (4, ("SP", "SPI")),  # or contains "SPIN"
    (5, ("FA", "FB", "FAS")),  # or contains "FAST"/"PACE"
    (6, ("UC", "UNC")),  # or contains "UNCAPPED"
]


def _parse_set_name(name: str) -> tuple[bool, int, int]:
    upper = name.upper().strip()
    is_marquee = upper.startswith("M") or "MARQUEE" in upper

    num_match = re.search(r"\d+", upper)
    round_num = int(num_match.group()) if num_match else 1

    category_priority = 7
    if upper.startswith(("BA", "BAT")):
        category_priority = 1
    elif upper.startswith(("AL", "AR")) or "ROUNDER" in upper:
        category_priority = 2
    elif upper.startswith(("WK", "WIC")) or "KEEPER" in upper:
        category_priority = 3
    elif upper.startswith(("SP", "SPI")) or "SPIN" in upper:
        category_priority = 4
    elif upper.startswith(("FA", "FB", "FAS")) or "FAST" in upper or "PACE" in upper:
        category_priority = 5
    elif upper.startswith(("UC", "UNC")) or "UNCAPPED" in upper:
        category_priority = 6

    return is_marquee, round_num, category_priority


def get_unique_sets(players: list[AuctionPlayer]) -> list[str]:
    unique = sorted(set(p.set_name for p in players if p.set_name))
    if not unique:
        return ["Marquee", "Batsman", "All-Rounder", "Wicketkeeper", "Spin Bowler", "Fast Bowler", "Uncapped"]

    def sort_key(name: str):
        is_marquee, round_num, category_priority = _parse_set_name(name)
        return (0 if is_marquee else 1, round_num, category_priority, name)

    return sorted(unique, key=sort_key)


def players_in_set(players: list[AuctionPlayer], set_name: str) -> list[AuctionPlayer]:
    return [p for p in players if p.set_name == set_name]
