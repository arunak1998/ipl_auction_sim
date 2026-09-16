"""
One COMPLETE auction through the live game engine, all 10 seats AI.

This deliberately drives game/auction_room.py -- the same code the browser
talks to -- rather than the training MDP, so the duel rule, the hammer
count, the bid noise and the set shuffling are all exercised exactly as a
real playthrough would.

The tenth seat is nominally "human"; here it is driven by the same trained
policy via the room's own proxy-bid mechanism, so all ten franchises bid.
"""
import pathlib
import sys
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from game.auction_room import AuctionRoom
from game.model_registry import ModelRegistry, TEAM_IDS
from rl.auction_mdp import PoolLookahead, build_observation, clip_willingness, same_caliber_left
from rl.fair_price import fair_price_cr
from rl.team_bot import bot_willingness, SQUAD_TARGET
from rl.squad_rules import best_xi, xi_strength, has_legal_xi

BUDGET = 125.0


def human_ceiling(room: AuctionRoom) -> float:
    """The 'human' seat's limit, from the same policy the AI teams use."""
    player = room.current_player
    seat = room.teams[room.human_team_id]
    fair = fair_price_cr(player)
    remaining = room._remaining_players()
    look = PoolLookahead(remaining, {p.player_id: fair_price_cr(p) for p in remaining}).features(-1)
    obs = build_observation(
        seat=seat, player=player, fair=fair,
        caliber_left=same_caliber_left(remaining, player),
        players_left=len(remaining), total_players=len(room.all_players), lookahead=look,
        include_pace_spin=room.model_registry.include_pace_spin(),
        team_variant=room.model_registry.team_variant(),
    )
    if room.model_registry.has_model(room.human_team_id):
        willing = room.model_registry.willingness_multiplier(obs) * fair
    else:
        willing = bot_willingness(seat, player, fair)
    willing *= room._rng.lognormvariate(0.0, 0.06)
    return clip_willingness(seat, willing, fair)


def play_lot(room: AuctionRoom) -> None:
    """Exactly the frontend's loop: tick, count, settle."""
    room.set_auto_bid(human_ceiling(room))
    stage = 0
    for _ in range(600):
        if stage > 3:
            room.settle_lot()
            return
        evs = room.ai_tick(allow_new_entrant=stage > 0)
        stage = 0 if evs else stage + 1
    room.settle_lot()


def main(seed: int = 2026) -> None:
    """Play one full auction and write backend/reports/auction_seed<N>.json."""
    room = AuctionRoom(TEAM_IDS[0], ModelRegistry())
    room._rng.seed(seed)

    lots = 0
    while room.get_available_sets():
        room.open_set(room.get_available_sets()[0])
        while room.current_player is not None and room.phase == "AUCTION_STAGE":
            play_lot(room)
            lots += 1

    if room.phase == "NOMINATION":
        room.launch_boost_round()
        while room.current_player is not None and room.phase == "BOOST_ROUND":
            play_lot(room)
            lots += 1

    print(f"AUCTION COMPLETE — {lots} lots, final phase {room.phase}\n")

    hdr = (f"{'Team':6s} {'Squad':>5s} {'Spent':>8s} {'Left':>7s} "
           f"{'BAT':>4s} {'WK':>3s} {'AR':>4s} {'PACE':>5s} {'SPIN':>5s} {'OS':>3s} "
           f"{'XI':>7s} {'LegalXI':>8s}")
    print(hdr); print("-" * len(hdr))

    totals = Counter()
    for tid in TEAM_IDS:
        seat = room.teams[tid]
        roles = Counter(p.role for p in seat.squad)
        subs = Counter(p.bowler_subtype for p in seat.squad if p.role == "Bowler")
        spent = BUDGET - seat.budget
        strength = xi_strength(seat.squad) * 11
        legal = "yes" if has_legal_xi(seat.squad) else "NO"
        totals["spent"] += spent
        totals["squad"] += len(seat.squad)
        if legal == "yes":
            totals["legal"] += 1
        print(f"{tid:6s} {len(seat.squad):5d} {spent:8.2f} {seat.budget:7.2f} "
              f"{roles['Batter']:4d} {roles['Wicketkeeper']:3d} {roles['All-rounder']:4d} "
              f"{subs['Pace']:5d} {subs['Spin']:5d} {seat.overseas_count:3d} "
              f"{strength:7.1f} {legal:>8s}")

    print("-" * len(hdr))
    print(f"{'TOTAL':6s} {totals['squad']:5d} {totals['spent']:8.2f} "
          f"{10*BUDGET - totals['spent']:7.2f}")
    print(f"\nteams with a legal XI: {totals['legal']}/10")
    print(f"mean purse used      : {100*totals['spent']/(10*BUDGET):.1f}%")

    import json
    out = {"lots": lots, "teams": []}
    for tid in TEAM_IDS:
        seat = room.teams[tid]
        roles = Counter(p.role for p in seat.squad)
        subs = Counter(p.bowler_subtype for p in seat.squad if p.role == "Bowler")
        xi = best_xi(seat.squad) or []
        # Mark the XI by OBJECT IDENTITY, not player_id. Matching on id
        # meant that if a squad ever held the same player twice, both
        # copies were flagged and the "XI" came back as twelve -- which is
        # exactly how the duplicate-purchase bug first showed up.
        xi_marked = {id(q) for q in xi}
        out["teams"].append({
            "id": tid,
            "squad_size": len(seat.squad),
            "spent": round(BUDGET - seat.budget, 2),
            "left": round(seat.budget, 2),
            "overseas": seat.overseas_count,
            "strength": round(xi_strength(seat.squad) * 11, 1),
            "legal_xi": has_legal_xi(seat.squad),
            "roles": {"Batter": roles["Batter"], "Wicketkeeper": roles["Wicketkeeper"],
                      "All-rounder": roles["All-rounder"], "Pace": subs["Pace"], "Spin": subs["Spin"]},
            "players": sorted([{
                "name": p.name, "role": p.role, "subtype": p.bowler_subtype,
                "country": p.country, "overseas": p.is_overseas,
                "price": round(room._price_paid(seat, p.player_id), 2),
                "rating": round(p.value_score, 1),
                "in_xi": id(p) in xi_marked,
            } for p in seat.squad], key=lambda d: -d["price"]),
        })
    # Refuse to write a result that is internally inconsistent. Every one
    # of these caught a real bug at some point in this project.
    problems = []
    all_ids: dict[str, list[str]] = {}
    for t in out["teams"]:
        names = [q["name"] for q in t["players"]]
        if len(names) != len(set(names)):
            dupes = sorted({n for n in names if names.count(n) > 1})
            problems.append(f"{t['id']}: duplicate players {dupes}")
        if t["squad_size"] != SQUAD_TARGET:
            problems.append(f"{t['id']}: {t['squad_size']} players, expected {SQUAD_TARGET}")
        n_xi = sum(1 for q in t["players"] if q["in_xi"])
        if t["legal_xi"] and n_xi != 11:
            problems.append(f"{t['id']}: {n_xi} players flagged in_xi, expected 11")
        if t["left"] < -1e-9:
            problems.append(f"{t['id']}: negative purse {t['left']}")
        for q in t["players"]:
            all_ids.setdefault(q["name"], []).append(t["id"])
    for nm, owners in all_ids.items():
        if len(owners) > 1:
            problems.append(f"{nm} owned by more than one team: {owners}")

    if problems:
        print("\nVALIDATION FAILED — not writing the result:")
        for pr in problems:
            print("   " + pr)
        raise SystemExit(1)
    print("\nvalidation: no duplicates, every squad 20 players, every legal XI exactly 11")

    pathlib.Path(__file__).with_name(f"auction_seed{seed}.json").write_text(json.dumps(out, indent=1))
    print(f"\nwrote auction_seed{seed}.json")

    print("\nMOST EXPENSIVE SIGNINGS")
    buys = []
    for tid in TEAM_IDS:
        seat = room.teams[tid]
        for p in seat.squad:
            buys.append((room._price_paid(seat, p.player_id), p.name, tid, p.role))
    for price, name, tid, role in sorted(buys, reverse=True)[:10]:
        print(f"   {price:6.2f} Cr  {name:24s} {tid:5s} {role}")


if __name__ == "__main__":
    # Seed on the command line: `python reports/play_full_auction.py 7`.
    # Every run with the same seed reproduces exactly; a different seed is a
    # genuinely different auction, because team ceilings carry per-lot noise
    # and the lot order inside each set is shuffled.
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)
