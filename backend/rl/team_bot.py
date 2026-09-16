"""
The franchise seat (TeamState) plus the scripted opponent's valuation rule.

The scripted bots are deliberately "flawed toys": archetypes that bid too
hard or too soft relative to the market, kept in the opponent mix at every
curriculum phase so the policy has to stay robust to opponents that aren't
just mirror images of itself.

Everything here is denominated in the ML model's FAIR PRICE, not base
price. That matters: the learned policy's action is a multiplier on fair
price, so the scripted bots must reason in the same units or the two sides
aren't playing the same game -- an earlier version priced bots off base
price, which made every marquee player (all sharing a nominal 2 Cr base)
indistinguishable to them.
"""

from __future__ import annotations

import random

from .data_loader import AuctionPlayer
from .squad_rules import fills_a_need

SQUAD_TARGET = 20
MAX_OVERSEAS = 8
MIN_BASE_PRICE_CR = 0.30
MAX_PER_ROLE = {"Batter": 8, "Bowler": 8, "All-rounder": 8, "Wicketkeeper": 4}

# Hard ceiling on what anyone may pay, as a multiple of the model's fair
# price. A backstop against pathological clears, not a shaping signal.
MAX_PRICE_TO_FAIR_MULTIPLIER = 4.0

ROLES = ("Batter", "Bowler", "All-rounder", "Wicketkeeper")

_MEAN_PRICE_TO_BASE_MULTIPLIER: float | None = None


class TeamState:
    """One franchise's seat. Used identically by the learning agent, the
    scripted bots, and self-play snapshots -- there is no separate agent
    seat type, so no behaviour can diverge between training and evaluation
    by construction."""

    def __init__(self, team_id: str, profile: dict, rng: random.Random | None = None):
        self.team_id = team_id
        self.profile = profile
        self.budget = float(profile.get("budget_cr", 125.0))
        self.squad: list[AuctionPlayer] = []
        self.bought: list[tuple[AuctionPlayer, float]] = []
        # Per-episode jitter, so a scripted archetype isn't perfectly
        # predictable across episodes.
        self.mood = (rng or random).uniform(0.85, 1.15)

    def role_count(self, role: str) -> int:
        return sum(1 for p in self.squad if p.role == role)

    @property
    def overseas_count(self) -> int:
        return sum(1 for p in self.squad if p.is_overseas)

    @property
    def slots_remaining(self) -> int:
        return SQUAD_TARGET - len(self.squad)

    def max_affordable(self) -> float:
        """Most this seat can spend on ONE player while still being able to
        buy a minimum-price player for every remaining slot."""
        reserve = max(0, self.slots_remaining - 1) * MIN_BASE_PRICE_CR
        return max(0.0, self.budget - reserve)

    def is_eligible_for(self, player: AuctionPlayer, price: float) -> bool:
        if self.slots_remaining <= 0:
            return False
        if player.is_overseas and self.overseas_count >= MAX_OVERSEAS:
            return False
        if self.role_count(player.role) >= MAX_PER_ROLE[player.role]:
            return False
        return price <= self.max_affordable()

    def buy(self, player: AuctionPlayer, price: float) -> None:
        self.squad.append(player)
        self.bought.append((player, price))
        self.budget -= price


def _mean_price_to_base_multiplier() -> float:
    global _MEAN_PRICE_TO_BASE_MULTIPLIER
    if _MEAN_PRICE_TO_BASE_MULTIPLIER is None:
        from .data_loader import load_team_profiles
        vals = [
            float(p.get("avg_price_to_base_multiplier") or 0.0)
            for p in load_team_profiles()
        ]
        vals = [v for v in vals if v > 0]
        _MEAN_PRICE_TO_BASE_MULTIPLIER = sum(vals) / len(vals) if vals else 1.0
    return _MEAN_PRICE_TO_BASE_MULTIPLIER


def aggression_factor(profile: dict) -> float:
    """How hard this franchise historically bids relative to the other nine.
    Centred on 1.0 by dividing by the ten-team mean, so it modulates the
    model's fair price rather than replacing it."""
    mult = float(profile.get("avg_price_to_base_multiplier") or 0.0)
    if mult <= 0:
        return 1.0
    return min(1.25, max(0.75, mult / _mean_price_to_base_multiplier()))


def role_pref_factor(profile: dict, role: str) -> float:
    """This franchise's historical spend share for the role, against an even
    25% split. >1 means they historically pay up for this role."""
    key = "All-Rounder" if role == "All-rounder" else role
    pct = float(profile.get("role_spend_distribution_pct", {}).get(key, 25.0))
    return min(1.5, max(0.6, pct / 25.0))


def bot_willingness(seat: TeamState, player: AuctionPlayer, fair: float) -> float:
    """What a scripted opponent will pay, in Crore."""
    willingness = fair * aggression_factor(seat.profile) * role_pref_factor(seat.profile, player.role) * seat.mood

    if fills_a_need(seat.squad, player):
        willingness *= 1.3
    elif seat.role_count(player.role) >= 4:
        willingness *= 0.5  # already deep here

    return min(willingness, seat.max_affordable(), fair * MAX_PRICE_TO_FAIR_MULTIPLIER)
