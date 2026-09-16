"""
Extracts player batting/bowling/fielding stats from the Cricsheet ball-by-ball
match archive (data/all_male/*.yaml), split into three buckets:

  - IPL           : competition == IPL (per README manifest)
  - INTL_T20      : international T20s (match_type IT20, or match_type T20
                    with team_type international)
  - OTHER_T20     : every other T20-format club competition (BBL, PSL, CPL,
                    SA20, ILT20, domestic T20 leagues, etc.)

Non-T20 matches (Test, ODI, ODM, MDM) are skipped without a full YAML parse
(only their header is scanned) to save time, since Test-match files are large
and irrelevant to this dataset.

Known limitations (see CLAUDE.md-adjacent notes in the plan discussion):
  - Cricsheet has no captain field at all -- not extracted.
  - Cricsheet has no wicketkeeper marker -- primary_role can only
    distinguish Batter / Bowler / All-rounder / Unknown.
  - "country" is approximated as the most common team a player represented
    in the INTL_T20 bucket; players with no international appearances get
    country = None.
  - Phase splits (powerplay/middle/death) are only computed for matches with
    info.overs == 20; non-standard-over matches still count toward career
    totals but not toward phase splits.

Output: 4 CSVs written to backend/data_pipeline/
  players_registry.csv, ipl_stats.csv, international_t20_stats.csv, other_t20_stats.csv
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "all_male"
OUT_DIR = Path(__file__).resolve().parent

DISMISSAL_CREDITED_TO_BOWLER = {
    "caught", "bowled", "lbw", "stumped", "hit wicket", "caught and bowled",
}

BUCKETS = ["IPL", "INTL_T20", "OTHER_T20"]
ALL_ROUNDER_INNINGS_THRESHOLD = 30
ALL_ROUNDER_RATIO = 0.4
WICKETKEEPER_STUMPING_THRESHOLD = 5


# --- Step 1: cheap header scan, no YAML parsing, to filter out non-T20 files ---

def quick_match_type(path: Path) -> str | None:
    with path.open("r", encoding="utf-8") as fh:
        for _ in range(40):
            line = fh.readline()
            if not line:
                break
            line = line.strip()
            if line.startswith("match_type:"):
                return line.split(":", 1)[1].strip()
            if line.startswith("players:") or line.startswith("registry:"):
                break
    return None


# --- Step 2: manifest (README.txt) gives team_type + competition code per match id ---

def read_manifest(readme_path: Path) -> dict[str, dict]:
    manifest: dict[str, dict] = {}
    with readme_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            parts = [p.strip() for p in line.split(" - ")]
            if len(parts) != 6:
                continue
            date_str, team_type, code, gender, match_id, _teams = parts
            if not match_id.isdigit():
                continue
            manifest[match_id] = {"date": date_str, "team_type": team_type, "code": code}
    return manifest


def determine_bucket(match_type: str, manifest_entry: dict | None) -> str:
    team_type = manifest_entry["team_type"] if manifest_entry else None
    code = manifest_entry["code"] if manifest_entry else None
    if match_type == "IT20" or team_type == "international":
        return "INTL_T20"
    if code == "IPL":
        return "IPL"
    return "OTHER_T20"


# --- Per-innings records (needed for milestones + "recent form") ---

@dataclass
class BattingInnings:
    player_id: str
    match_date: str
    runs: int = 0
    balls_faced: int = 0
    dismissed: bool = False
    fours: int = 0
    sixes: int = 0
    dots: int = 0
    pp_runs: int = 0
    pp_balls: int = 0
    mid_runs: int = 0
    mid_balls: int = 0
    death_runs: int = 0
    death_balls: int = 0


@dataclass
class BowlingInnings:
    player_id: str
    match_date: str
    balls_bowled: int = 0
    runs_conceded: int = 0
    wickets: int = 0
    dot_balls: int = 0
    fours_conceded: int = 0
    sixes_conceded: int = 0
    pp_balls: int = 0
    pp_runs: int = 0
    pp_wkts: int = 0
    mid_balls: int = 0
    mid_runs: int = 0
    mid_wkts: int = 0
    death_balls: int = 0
    death_runs: int = 0
    death_wkts: int = 0


@dataclass
class PlayerAccumulator:
    name: str = ""
    batting: list = field(default_factory=list)
    bowling: list = field(default_factory=list)
    # Each entry is the match_date of that dismissal (not just a running count)
    # so a year-cutoff snapshot can filter these the same way as innings.
    catches: list = field(default_factory=list)
    run_outs: list = field(default_factory=list)
    stumpings: list = field(default_factory=list)
    teams: Counter = field(default_factory=Counter)
    competitions: set = field(default_factory=set)
    match_dates: list = field(default_factory=list)


def phase_of_over(over_1_indexed: int) -> str:
    if over_1_indexed <= 6:
        return "pp"
    if over_1_indexed <= 15:
        return "mid"
    return "death"


def process_match(data: dict, bucket: str, match_date: str, acc: dict[str, PlayerAccumulator], names_seen: dict[str, str]) -> None:
    info = data.get("info", {})
    # Some Cricsheet ids are all-digit hex strings (e.g. "12345678"); PyYAML's
    # implicit typing parses those as int instead of str, so normalize here.
    registry = {name: str(pid) for name, pid in info.get("registry", {}).get("people", {}).items()}
    players_by_team = info.get("players", {})
    is_standard_overs = info.get("overs") == 20

    name_to_team = {}
    for team, names in players_by_team.items():
        for name in names:
            name_to_team[name] = team

    def get_id(name: str) -> str | None:
        return registry.get(name)

    def ensure(pid: str, name: str) -> PlayerAccumulator:
        if pid not in acc:
            acc[pid] = PlayerAccumulator(name=name)
        names_seen[pid] = name
        return acc[pid]

    competition_name = info.get("competition")

    for name, pid in registry.items():
        if pid is None:
            continue
        p = ensure(pid, name)
        team = name_to_team.get(name)
        if team:
            p.teams[team] += 1
        if competition_name:
            p.competitions.add(competition_name)
        p.match_dates.append(match_date)

    for innings in data.get("innings", []):
        for _label, innings_data in innings.items():
            deliveries = innings_data.get("deliveries", [])
            bat_innings: dict[str, BattingInnings] = {}
            bowl_innings: dict[str, BowlingInnings] = {}

            for delivery_entry in deliveries:
                for over_ball_key, ball in delivery_entry.items():
                    over_num = int(str(over_ball_key).split(".")[0]) + 1
                    phase = phase_of_over(over_num) if is_standard_overs else None

                    batsman_name = ball.get("batsman")
                    bowler_name = ball.get("bowler")
                    runs = ball.get("runs", {})
                    extras = ball.get("extras", {}) or {}
                    batsman_runs = runs.get("batsman", 0)
                    total_runs = runs.get("total", 0)
                    is_wide = "wides" in extras
                    is_noball = "noballs" in extras

                    bat_id = get_id(batsman_name) if batsman_name else None
                    bowl_id = get_id(bowler_name) if bowler_name else None

                    if bat_id:
                        bi = bat_innings.setdefault(bat_id, BattingInnings(bat_id, match_date))
                        if not is_wide:
                            bi.balls_faced += 1
                            if batsman_runs == 0:
                                bi.dots += 1
                            if phase == "pp":
                                bi.pp_balls += 1
                            elif phase == "mid":
                                bi.mid_balls += 1
                            elif phase == "death":
                                bi.death_balls += 1
                        bi.runs += batsman_runs
                        if phase == "pp":
                            bi.pp_runs += batsman_runs
                        elif phase == "mid":
                            bi.mid_runs += batsman_runs
                        elif phase == "death":
                            bi.death_runs += batsman_runs
                        if batsman_runs == 4:
                            bi.fours += 1
                        elif batsman_runs == 6:
                            bi.sixes += 1

                    if bowl_id:
                        bwi = bowl_innings.setdefault(bowl_id, BowlingInnings(bowl_id, match_date))
                        if not is_wide and not is_noball:
                            bwi.balls_bowled += 1
                            if phase == "pp":
                                bwi.pp_balls += 1
                            elif phase == "mid":
                                bwi.mid_balls += 1
                            elif phase == "death":
                                bwi.death_balls += 1
                            if total_runs == 0:
                                bwi.dot_balls += 1
                        if batsman_runs == 4:
                            bwi.fours_conceded += 1
                        elif batsman_runs == 6:
                            bwi.sixes_conceded += 1
                        byes_legbyes = extras.get("byes", 0) + extras.get("legbyes", 0)
                        bowler_conceded = total_runs - byes_legbyes
                        bwi.runs_conceded += bowler_conceded
                        if phase == "pp":
                            bwi.pp_runs += bowler_conceded
                        elif phase == "mid":
                            bwi.mid_runs += bowler_conceded
                        elif phase == "death":
                            bwi.death_runs += bowler_conceded

                    wicket_raw = ball.get("wicket")
                    # Cricsheet normally has one wicket dict per ball, but rarely
                    # (e.g. a run out off a no-ball) represents two as a list.
                    wickets = wicket_raw if isinstance(wicket_raw, list) else ([wicket_raw] if wicket_raw else [])
                    for wicket in wickets:
                        kind = wicket.get("kind")
                        player_out = wicket.get("player_out")
                        out_id = get_id(player_out) if player_out else None
                        if out_id and out_id in bat_innings:
                            bat_innings[out_id].dismissed = True
                        elif out_id:
                            bi = bat_innings.setdefault(out_id, BattingInnings(out_id, match_date))
                            bi.dismissed = True

                        if kind in DISMISSAL_CREDITED_TO_BOWLER and bowl_id and bowl_id in bowl_innings:
                            bowl_innings[bowl_id].wickets += 1
                            if phase == "pp":
                                bowl_innings[bowl_id].pp_wkts += 1
                            elif phase == "mid":
                                bowl_innings[bowl_id].mid_wkts += 1
                            elif phase == "death":
                                bowl_innings[bowl_id].death_wkts += 1

                        fielders = wicket.get("fielders") or []
                        if kind == "caught and bowled" and bowler_name:
                            fid = get_id(bowler_name)
                            if fid:
                                ensure(fid, bowler_name).catches.append(match_date)
                        else:
                            for fielder_name in fielders:
                                fid = get_id(fielder_name)
                                if not fid:
                                    continue
                                p = ensure(fid, fielder_name)
                                if kind == "caught":
                                    p.catches.append(match_date)
                                elif kind == "stumped":
                                    p.stumpings.append(match_date)
                                elif kind == "run out":
                                    p.run_outs.append(match_date)

            for pid, bi in bat_innings.items():
                ensure(pid, names_seen.get(pid, "")).batting.append(bi)
            for pid, bwi in bowl_innings.items():
                ensure(pid, names_seen.get(pid, "")).bowling.append(bwi)


def load_yaml(path: Path) -> dict:
    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    with path.open("r", encoding="utf-8") as fh:
        return yaml.load(fh, Loader=loader)


def build_stats_row(pid: str, name: str, bucket: str, acc: PlayerAccumulator) -> dict:
    batting = acc.batting
    bowling = acc.bowling

    innings_batted = len(batting)
    runs = sum(b.runs for b in batting)
    balls_faced = sum(b.balls_faced for b in batting)
    dismissals = sum(1 for b in batting if b.dismissed)
    not_outs = innings_batted - dismissals
    fours = sum(b.fours for b in batting)
    sixes = sum(b.sixes for b in batting)
    batting_dots = sum(b.dots for b in batting)
    hundreds = sum(1 for b in batting if b.runs >= 100)
    fifties = sum(1 for b in batting if 50 <= b.runs < 100)
    thirties = sum(1 for b in batting if 30 <= b.runs < 50)
    ducks = sum(1 for b in batting if b.runs == 0 and b.dismissed)
    highest_score = max((b.runs for b in batting), default=0)

    pp_runs = sum(b.pp_runs for b in batting)
    pp_balls = sum(b.pp_balls for b in batting)
    mid_runs = sum(b.mid_runs for b in batting)
    mid_balls = sum(b.mid_balls for b in batting)
    death_runs = sum(b.death_runs for b in batting)
    death_balls = sum(b.death_balls for b in batting)

    recent_batting = sorted(batting, key=lambda b: b.match_date, reverse=True)[:10]
    recent_runs = sum(b.runs for b in recent_batting)
    recent_balls = sum(b.balls_faced for b in recent_batting)
    recent_dismissals = sum(1 for b in recent_batting if b.dismissed)

    innings_bowled = len(bowling)
    balls_bowled = sum(b.balls_bowled for b in bowling)
    runs_conceded = sum(b.runs_conceded for b in bowling)
    wickets = sum(b.wickets for b in bowling)
    dot_balls = sum(b.dot_balls for b in bowling)
    fours_conceded = sum(b.fours_conceded for b in bowling)
    sixes_conceded = sum(b.sixes_conceded for b in bowling)
    four_wicket_hauls = sum(1 for b in bowling if b.wickets == 4)
    five_wicket_hauls = sum(1 for b in bowling if b.wickets >= 5)
    best = max(bowling, key=lambda b: (b.wickets, -b.runs_conceded), default=None)
    best_bowling = f"{best.wickets}/{best.runs_conceded}" if best else ""

    pp_wkts = sum(b.pp_wkts for b in bowling)
    pp_bowl_balls = sum(b.pp_balls for b in bowling)
    pp_bowl_runs = sum(b.pp_runs for b in bowling)
    mid_wkts = sum(b.mid_wkts for b in bowling)
    mid_bowl_balls = sum(b.mid_balls for b in bowling)
    mid_bowl_runs = sum(b.mid_runs for b in bowling)
    death_wkts = sum(b.death_wkts for b in bowling)
    death_bowl_balls = sum(b.death_balls for b in bowling)
    death_bowl_runs = sum(b.death_runs for b in bowling)

    recent_bowling = sorted(bowling, key=lambda b: b.match_date, reverse=True)[:10]
    recent_wickets = sum(b.wickets for b in recent_bowling)
    recent_conceded = sum(b.runs_conceded for b in recent_bowling)
    recent_bowl_balls = sum(b.balls_bowled for b in recent_bowling)

    dates = sorted(acc.match_dates)

    def safe_div(n, d):
        return round(n / d, 2) if d else None

    return {
        "player_id": pid,
        "player_name": name,
        "bucket": bucket,
        "matches_played": len(set(dates)),
        "first_match_date": dates[0] if dates else "",
        "last_match_date": dates[-1] if dates else "",
        "teams_played_for": ", ".join(sorted(acc.teams)),
        "competitions_played": ", ".join(sorted(acc.competitions)),

        "innings_batted": innings_batted,
        "runs": runs,
        "balls_faced": balls_faced,
        "dismissals": dismissals,
        "not_outs": not_outs,
        "batting_average": safe_div(runs, dismissals),
        "batting_strike_rate": safe_div(runs * 100, balls_faced),
        "highest_score": highest_score,
        "hundreds": hundreds,
        "fifties": fifties,
        "thirties": thirties,
        "ducks": ducks,
        "fours": fours,
        "sixes": sixes,
        "boundary_percentage": safe_div((fours * 4 + sixes * 6) * 100, runs),
        "batting_dot_ball_pct": safe_div(batting_dots * 100, balls_faced),

        "pp_runs": pp_runs, "pp_balls_faced": pp_balls, "pp_strike_rate": safe_div(pp_runs * 100, pp_balls),
        "middle_runs": mid_runs, "middle_balls_faced": mid_balls, "middle_strike_rate": safe_div(mid_runs * 100, mid_balls),
        "death_runs": death_runs, "death_balls_faced": death_balls, "death_strike_rate": safe_div(death_runs * 100, death_balls),

        "recent_runs": recent_runs,
        "recent_average": safe_div(recent_runs, recent_dismissals),
        "recent_strike_rate": safe_div(recent_runs * 100, recent_balls),

        "innings_bowled": innings_bowled,
        "balls_bowled": balls_bowled,
        "runs_conceded": runs_conceded,
        "wickets": wickets,
        "bowling_average": safe_div(runs_conceded, wickets) if wickets else None,
        "economy": safe_div(runs_conceded * 6, balls_bowled),
        "bowling_strike_rate": safe_div(balls_bowled, wickets) if wickets else None,
        "best_bowling": best_bowling,
        "four_wicket_hauls": four_wicket_hauls,
        "five_wicket_hauls": five_wicket_hauls,
        "dot_ball_pct": safe_div(dot_balls * 100, balls_bowled),
        "fours_conceded": fours_conceded,
        "sixes_conceded": sixes_conceded,
        "boundary_pct_conceded": safe_div((fours_conceded + sixes_conceded) * 100, balls_bowled),

        "pp_wickets": pp_wkts, "pp_balls_bowled": pp_bowl_balls, "pp_economy": safe_div(pp_bowl_runs * 6, pp_bowl_balls),
        "middle_wickets": mid_wkts, "middle_balls_bowled": mid_bowl_balls, "middle_economy": safe_div(mid_bowl_runs * 6, mid_bowl_balls),
        "death_wickets": death_wkts, "death_balls_bowled": death_bowl_balls, "death_economy": safe_div(death_bowl_runs * 6, death_bowl_balls),

        "recent_wickets": recent_wickets,
        "recent_economy": safe_div(recent_conceded * 6, recent_bowl_balls),
        "recent_bowling_average": safe_div(recent_conceded, recent_wickets) if recent_wickets else None,

        "catches": len(acc.catches),
        "run_outs": len(acc.run_outs),
        "stumpings": len(acc.stumpings),
    }


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_all_matches() -> tuple[dict[str, dict[str, PlayerAccumulator]], dict[str, str]]:
    """Scans every match file once and returns the full (uncut) per-player
    accumulators. This is the expensive step (~3 min) -- callers that need
    stats as-of a specific date (e.g. a year-cutoff analysis) should call
    this once and filter the returned accumulators' innings lists by date,
    rather than re-parsing the raw files per cutoff."""
    manifest = read_manifest(DATA_DIR / "README.txt")
    files = sorted(DATA_DIR.glob("*.yaml"))

    bucket_acc: dict[str, dict[str, PlayerAccumulator]] = {b: {} for b in BUCKETS}
    names_seen: dict[str, str] = {}

    processed = 0
    skipped_non_short_format = 0
    parse_failures = 0

    for i, path in enumerate(files):
        match_type = quick_match_type(path)
        if match_type not in ("T20", "IT20"):
            skipped_non_short_format += 1
            continue

        match_id = path.stem
        manifest_entry = manifest.get(match_id)
        bucket = determine_bucket(match_type, manifest_entry)

        try:
            data = load_yaml(path)
        except yaml.YAMLError as exc:
            print(f"WARN: failed to parse {path.name}: {exc}")
            parse_failures += 1
            continue

        match_date = (manifest_entry["date"] if manifest_entry else None) or str(
            (data.get("info", {}).get("dates") or [""])[0]
        )
        process_match(data, bucket, match_date, bucket_acc[bucket], names_seen)

        processed += 1
        if processed % 1000 == 0:
            print(f"...processed {processed} short-format matches ({i + 1}/{len(files)} files scanned)")

    print(
        f"Done scanning {len(files)} files: {processed} short-format matches processed, "
        f"{skipped_non_short_format} non-short-format skipped, {parse_failures} parse failures."
    )
    return bucket_acc, names_seen


def classify_role(total_batted: int, total_bowled: int, total_stumpings: int) -> str:
    is_all_rounder = (
        total_batted >= ALL_ROUNDER_INNINGS_THRESHOLD
        and total_bowled >= ALL_ROUNDER_INNINGS_THRESHOLD
        and min(total_batted, total_bowled) / max(total_batted, total_bowled) >= ALL_ROUNDER_RATIO
    )
    # Only a wicketkeeper is ever credited with a stumping, so this is an
    # unambiguous signal (unlike the all-rounder heuristic above) -- checked
    # first since keeping is the more defining trait.
    if total_stumpings >= WICKETKEEPER_STUMPING_THRESHOLD:
        return "Wicketkeeper"
    if is_all_rounder:
        return "All-rounder"
    if total_bowled > total_batted:
        return "Bowler"
    if total_batted > 0:
        return "Batter"
    return "Unknown"


def build_registry(bucket_acc: dict[str, dict[str, PlayerAccumulator]], names_seen: dict[str, str]) -> list[dict]:
    """Builds the registry, dropping "Unknown"-role entries (umpires/officials
    and players who never recorded a ball faced or bowled -- see module
    docstring). Returns only classifiable players."""
    all_pids = set()
    for b in BUCKETS:
        all_pids.update(bucket_acc[b].keys())

    rows = []
    for pid in sorted(all_pids):
        total_batted = sum(len(bucket_acc[b][pid].batting) for b in BUCKETS if pid in bucket_acc[b])
        total_bowled = sum(len(bucket_acc[b][pid].bowling) for b in BUCKETS if pid in bucket_acc[b])
        total_stumpings = sum(len(bucket_acc[b][pid].stumpings) for b in BUCKETS if pid in bucket_acc[b])
        role = classify_role(total_batted, total_bowled, total_stumpings)
        if role == "Unknown":
            continue

        intl_acc = bucket_acc["INTL_T20"].get(pid)
        country = intl_acc.teams.most_common(1)[0][0] if intl_acc and intl_acc.teams else ""

        rows.append({"player_id": pid, "player_name": names_seen.get(pid, ""), "country": country, "primary_role": role})
    return rows


def main() -> None:
    bucket_acc, names_seen = parse_all_matches()

    registry_rows = build_registry(bucket_acc, names_seen)
    known_pids = {r["player_id"] for r in registry_rows}
    write_csv(OUT_DIR / "players_registry.csv", registry_rows)
    print(f"players_registry.csv: {len(registry_rows)} players")

    filenames = {
        "IPL": "ipl_stats.csv",
        "INTL_T20": "international_t20_stats.csv",
        "OTHER_T20": "other_t20_stats.csv",
    }
    for b in BUCKETS:
        rows = [
            build_stats_row(pid, names_seen.get(pid, ""), b, acc)
            for pid, acc in bucket_acc[b].items()
            if pid in known_pids
        ]
        write_csv(OUT_DIR / filenames[b], rows)
        print(f"{filenames[b]}: {len(rows)} players")


if __name__ == "__main__":
    main()
