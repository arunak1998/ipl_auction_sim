"""
Maps the 620-player auction pool (data/IPL_2025_Retained_Players_Detailed.csv)
to Cricsheet's canonical player registry (players_registry.csv) by IDENTITY,
not by name heuristics -- replacing the surname+initials matcher that
collapsed distinct players sharing a surname and first initial (Rohit Sharma
vs Rituraj Sharma, Suryakumar Yadav vs Sonu/Siddharth/Sanjay Yadav, etc).

Every downstream join (value_score, pace/spin subtype, fair price) should key
off player_id from the resulting player_id_map.csv, not off names -- name
matching becomes a one-time mapping step here, done once and persisted, not a
runtime heuristic repeated on every load.

Tiered matching, cheapest/safest first:
  Tier 1: exact normalized-name match against the registry. If more than one
          registry row shares that name, disambiguate by country if that
          narrows it to exactly one; otherwise it's ambiguous.
  Tier 1b: exact match on an ABBREVIATED form of the auction name ("Ruturaj
          Gaikwad" -> "R Gaikwad") against the registry. Cricsheet's own
          registry stores a large fraction of players under exactly this
          initials+surname form rather than a full first name (confirmed by
          spot-checking Tier-3 fallouts: "Ruturaj Gaikwad" only scored 72/100
          against the registry's actual "RD Gaikwad" under plain fuzzy
          matching on the full string -- a format mismatch, not a real
          difference). This tries the SAME exact-match-or-ambiguous
          discipline as Tier 1, just against a better-shaped candidate
          string, so it isn't the initials-collision heuristic this whole
          rewrite exists to replace: a name that abbreviates to something
          shared by more than one registry row still falls through to
          ambiguous, exactly like Tier 1.
  Tier 2: fuzzy match (rapidfuzz token_sort_ratio) against every registry
          name, tried on BOTH the full name and the abbreviated form,
          auto-accepted only if exactly one candidate (pooled across both)
          clears FUZZY_THRESHOLD -- catches spelling variants (Kuldip/
          Kuldeep Yadav, Ravichandaran/Ravichandran Ashwin) without guessing
          between two real candidates.
  Tier 3: no candidate, or more than one candidate this confident -- written
          to a review file for manual resolution. Never guessed.

Run from backend/ as:  uv run python -m data_pipeline.build_player_id_map
Output:
  data_pipeline/player_id_map.csv     -- one row per auction player: name,
                                          matched player_id (blank if none),
                                          tier, match confidence, registry name
  data_pipeline/player_id_map_review.csv -- only the Tier 3 rows, for manual
                                             resolution before this map is
                                             trusted as complete
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DIR = Path(__file__).resolve().parent

FUZZY_THRESHOLD = 93.0
FUZZY_THRESHOLD_WITH_COUNTRY = 85.0


def normalize(name: str) -> str:
    name = str(name).strip().lower()
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    name = name.replace(".", "").replace("-", " ")
    return " ".join(name.split())


# Same country, different spelling in the two data sources -- without this,
# a real conflict check would wrongly flag e.g. "USA" (auction) vs "United
# States of America" (registry) as a mismatch.
COUNTRY_ALIASES = {"usa": "united states of america", "us": "united states of america"}


def normalize_country(country: object) -> str | None:
    if not isinstance(country, str) or not country.strip():
        return None
    c = country.strip().lower()
    return COUNTRY_ALIASES.get(c, c)


def country_conflicts(auction_country: object, registry_country: object) -> bool:
    """True only when BOTH sides have a known country and they genuinely
    differ -- an unknown country on either side is not evidence of
    anything, so it never blocks a match on its own."""
    ac, rc = normalize_country(auction_country), normalize_country(registry_country)
    return ac is not None and rc is not None and ac != rc


def abbreviated_form(norm_name: str) -> str:
    """'ruturaj gaikwad' -> 'r gaikwad' -- the shape Cricsheet's own
    registry stores many players under (initials + surname), independent
    of whether OUR auction data happens to carry the full given name."""
    parts = norm_name.split()
    if len(parts) < 2:
        return norm_name
    return "".join(p[0] for p in parts[:-1]) + " " + parts[-1]


def main() -> None:
    auction = pd.read_csv(DATA_DIR / "IPL_2025_Retained_Players_Detailed.csv")
    registry = pd.read_csv(DIR / "players_registry.csv", dtype=str)
    registry["norm_name"] = registry["player_name"].apply(normalize)

    by_norm_name: dict[str, list[int]] = {}
    for idx, norm in registry["norm_name"].items():
        by_norm_name.setdefault(norm, []).append(idx)

    registry_names = registry["norm_name"].tolist()

    rows = []
    for _, player in auction.iterrows():
        full_name = player["Full Name"]
        country = player["Country"]
        norm = normalize(full_name)

        tier = None
        player_id = ""
        matched_name = ""
        confidence = ""
        note = ""

        abbrev = abbreviated_form(norm)

        def _resolve_exact(key: str) -> list[int]:
            return by_norm_name.get(key, [])

        exact_idxs = _resolve_exact(norm)
        if len(exact_idxs) == 1:
            # A single exact-name match is NOT automatically safe -- two
            # different real people can share a full name (e.g. two
            # unrelated "Mohit Sharma"s). If the registry candidate's
            # country is known and conflicts with the auction player's,
            # this isn't a match at all; fall through instead of accepting
            # it (this is what let "Steve Smith" (Australia) silently
            # attach to an unrelated Bermudian "S Smith" before).
            if country_conflicts(country, registry.at[exact_idxs[0], "country"]):
                idx = None
            else:
                tier, idx = "1-exact", exact_idxs[0]
        elif len(exact_idxs) > 1:
            # Disambiguate by country if that narrows it to exactly one.
            country_matches = [
                i for i in exact_idxs
                if isinstance(registry.at[i, "country"], str) and registry.at[i, "country"].lower() == str(country).lower()
            ]
            if len(country_matches) == 1:
                tier, idx = "1-exact+country", country_matches[0]
            else:
                tier, idx = "3-ambiguous", None
                note = f"{len(exact_idxs)} registry rows share this exact name; country didn't disambiguate"
        else:
            idx = None

        if tier is None and abbrev != norm:
            # Tier 1b: exact match on the abbreviated (initials+surname)
            # form -- same country-conflict veto as Tier 1 above.
            abbrev_idxs = _resolve_exact(abbrev)
            if len(abbrev_idxs) == 1:
                if country_conflicts(country, registry.at[abbrev_idxs[0], "country"]):
                    pass
                else:
                    tier, idx = "1b-abbrev-exact", abbrev_idxs[0]
            elif len(abbrev_idxs) > 1:
                tier, idx = "3-ambiguous", None
                note = f"{len(abbrev_idxs)} registry rows share the abbreviated form {abbrev!r}"

        if tier is None:
            # Tier 2: fuzzy match against every registry name, tried on BOTH
            # the full name and the abbreviated form -- e.g. "Ruturaj
            # Gaikwad" only scores 72/100 against the registry's actual "RD
            # Gaikwad" as full strings (format mismatch: full given name vs
            # initials), but its abbreviated form "R Gaikwad" scores much
            # higher against the same target. Candidates from both queries
            # are pooled and deduplicated by registry row before the same
            # exactly-one-strong-candidate discipline is applied.
            #
            # Country is used two ways, not just as a Tier-1 tiebreaker:
            # a KNOWN conflict (auction says India, candidate says Pakistan)
            # hard-excludes that candidate regardless of string score --
            # this is what catches "Mohammad Shami" (India) very nearly
            # matching "Mohammad Sami" (Pakistan, a different real player)
            # at a HIGHER string-similarity score (96.3) than the actually
            # correct "Mohammed Shami" (India, 92.9) -- pure string distance
            # ranked the wrong person first. A country AGREEMENT is treated
            # as independent corroboration and allowed a lower acceptance
            # bar (FUZZY_THRESHOLD_WITH_COUNTRY) than a string-only match,
            # since two independent signals agreeing is safer than one
            # signal alone scoring higher.
            pooled: dict[int, float] = {}
            for query in {norm, abbrev}:
                for name, score, _ in process.extract(query, registry_names, scorer=fuzz.token_sort_ratio, limit=5):
                    for candidate_idx in by_norm_name[name]:
                        cand_country = registry.at[candidate_idx, "country"]
                        if (
                            isinstance(cand_country, str)
                            and isinstance(country, str)
                            and cand_country.lower() != country.lower()
                        ):
                            continue  # known country conflict -- hard exclude
                        pooled[candidate_idx] = max(pooled.get(candidate_idx, 0.0), score)

            def _threshold_for(candidate_idx: int) -> float:
                cand_country = registry.at[candidate_idx, "country"]
                if isinstance(cand_country, str) and isinstance(country, str) and cand_country.lower() == country.lower():
                    return FUZZY_THRESHOLD_WITH_COUNTRY
                return FUZZY_THRESHOLD

            ranked = sorted(pooled.items(), key=lambda kv: -kv[1])
            top_score = ranked[0][1] if ranked else 0.0
            strong = [kv for kv in ranked if kv[1] >= _threshold_for(kv[0])]
            if len(strong) == 1:
                tier, idx = "2-fuzzy", strong[0][0]
                confidence = f"{strong[0][1]:.1f}"
            elif len(strong) > 1:
                tier, idx = "3-ambiguous", None
                note = f"{len(strong)} fuzzy candidates >= {FUZZY_THRESHOLD}: " + ", ".join(
                    f"{registry.at[i, 'player_name']}({s:.0f})" for i, s in strong
                )
            else:
                tier, idx = "3-nomatch", None
                best = registry.at[ranked[0][0], "player_name"] if ranked else "none"
                note = f"best fuzzy candidate only {top_score:.1f}: {best}"

        if idx is not None:
            player_id = registry.at[idx, "player_id"]
            matched_name = registry.at[idx, "player_name"]

        rows.append({
            "auction_name": full_name,
            "auction_role": player["Role"],
            "auction_country": country,
            "player_id": player_id,
            "matched_registry_name": matched_name,
            "tier": tier,
            "confidence": confidence,
            "note": note,
        })

    result = pd.DataFrame(rows)
    result.to_csv(DIR / "player_id_map.csv", index=False)

    tier_counts = result["tier"].value_counts()
    resolved = result["player_id"] != ""
    print(f"Total auction players: {len(result)}")
    print(f"Resolved to a registry player_id: {resolved.sum()} ({100*resolved.mean():.1f}%)")
    print(f"Unresolved (Tier 3, need manual review): {(~resolved).sum()}")
    print("\nBy tier:")
    for tier, count in tier_counts.items():
        print(f"  {tier:20s} {count:4d}")

    review = result[result["tier"].str.startswith("3-")]
    review.to_csv(DIR / "player_id_map_review.csv", index=False)
    print(f"\nReview file -> {DIR / 'player_id_map_review.csv'} ({len(review)} rows)")


if __name__ == "__main__":
    main()
