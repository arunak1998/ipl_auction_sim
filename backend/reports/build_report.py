"""
Render an auction_seed<N>.json result into a standalone HTML sheet.

    python reports/build_report.py 7

Reads reports/auction_seed<N>.json (written by play_full_auction.py) and
writes reports/auction_seed<N>.html beside it.
"""
import html
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent

# Real franchise colours, lightened where the brand colour is too dark to
# read as a stripe on a near-black ground.
META = {
    "csk": ("Chennai Super Kings", "#F9CD05"), "mi": ("Mumbai Indians", "#3E7BC8"),
    "rcb": ("Royal Challengers Bengaluru", "#EC1C24"), "kkr": ("Kolkata Knight Riders", "#7A5BA8"),
    "srh": ("Sunrisers Hyderabad", "#FF822A"), "rr": ("Rajasthan Royals", "#EA1A85"),
    "dc": ("Delhi Capitals", "#4A7BD4"), "pbks": ("Punjab Kings", "#DD1F2D"),
    "gt": ("Gujarat Titans", "#5BA3C7"), "lsg": ("Lucknow Super Giants", "#38A3F0"),
}
BUDGET = 125.0


def role_label(p: dict) -> str:
    """Pace/Spin only ever labels a SPECIALIST bowler.

    The source CSV records a bowling style for many batters who bowl a few
    part-time overs, so showing the subtype for every player would put
    "Pace" next to Virat Kohli and "Spin" next to MS Dhoni.
    """
    if p["role"] == "Bowler":
        return {"Pace": "Pace", "Spin": "Spin"}.get(p["subtype"], "Bowler")
    return {"Batter": "Bat", "Wicketkeeper": "WK", "All-rounder": "All-r"}[p["role"]]


def build(seed: int) -> pathlib.Path:
    data = json.loads((HERE / f"auction_seed{seed}.json").read_text())
    teams = sorted(data["teams"], key=lambda t: -t["strength"])
    spent_total = sum(t["spent"] for t in teams)
    legal = sum(1 for t in teams if t["legal_xi"])
    sold = sum(len(t["players"]) for t in teams)

    rows = []
    for i, t in enumerate(teams, 1):
        name, col = META[t["id"]]
        r = t["roles"]
        pct = t["spent"] / BUDGET * 100
        status = '<span class="ok">legal</span>' if t["legal_xi"] else '<span class="bad">no XI</span>'
        rows.append(
            f'<tr><td class="rank">{i}</td>'
            f'<td class="team"><span class="stripe" style="background:{col}"></span>'
            f'<span class="tname">{html.escape(name)}</span>'
            f'<span class="tabbr">{t["id"].upper()}</span></td>'
            f'<td class="num strong">{t["strength"]:.0f}</td>'
            f'<td class="num">{t["squad_size"]}</td>'
            f'<td class="purse"><div class="bar"><i style="width:{pct:.1f}%;background:{col}"></i></div>'
            f'<span class="num spent">{t["spent"]:.2f}</span></td>'
            f'<td class="num dim">{t["left"]:.2f}</td>'
            f'<td class="num">{r["Batter"]}</td><td class="num">{r["Wicketkeeper"]}</td>'
            f'<td class="num">{r["All-rounder"]}</td><td class="num">{r["Pace"]}</td>'
            f'<td class="num">{r["Spin"]}</td><td class="num">{t["overseas"]}</td>'
            f"<td>{status}</td></tr>"
        )

    panels = []
    for t in teams:
        name, col = META[t["id"]]
        items = []
        for p in t["players"]:
            flag = '<span class="os" title="Overseas">&#9992;</span>' if p["overseas"] else ""
            items.append(
                f'<li class="{"xi" if p["in_xi"] else ""}">'
                f'<span class="pn">{html.escape(p["name"])}{flag}</span>'
                f'<span class="pr">{role_label(p)}</span>'
                f'<span class="pv">{p["rating"]:.0f}</span>'
                f'<span class="pp">{p["price"]:.2f}</span></li>'
            )
        panels.append(
            f'<section class="squad" style="--team:{col}"><header>'
            f"<h3>{html.escape(name)}</h3><p class=\"meta\">"
            f'<b>{t["strength"]:.0f}</b> XI strength &middot; <b>{t["spent"]:.2f}</b> Cr spent '
            f'&middot; <b>{t["left"]:.2f}</b> Cr left &middot; <b>{t["overseas"]}</b>/8 overseas'
            f'</p></header><ol class="plist">{"".join(items)}</ol></section>'
        )

    tops = sorted(
        ((p["price"], p["name"], t["id"], role_label(p)) for t in teams for p in t["players"]),
        reverse=True,
    )[:8]
    top_html = "".join(
        f'<li><span class="tp">{pr:.2f}</span><span class="tn">{html.escape(n)}</span>'
        f'<span class="tt" style="color:{META[tid][1]}">{tid.upper()}</span>'
        f'<span class="tr">{rl}</span></li>'
        for pr, n, tid, rl in tops
    )

    doc = TEMPLATE.format(
        seed=seed, lots=data["lots"], sold=sold, spent=spent_total,
        used=spent_total / (10 * BUDGET) * 100, legal=legal,
        rows="".join(rows), panels="".join(panels), tops=top_html,
    )
    out = HERE / f"auction_seed{seed}.html"
    out.write_text(doc, encoding="utf-8")
    return out


TEMPLATE = """<title>IPL 2026 Auction Sheet</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Oswald:wght@400;600&family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>
:root{{
 --ground:#0a0e17; --panel:#10151f; --panel2:#0d121c; --line:#1e2a3d; --line-soft:#161f2e;
 --ink:#e8eef7; --ink-2:#9fb0c7; --ink-3:#63748c;
 --accent:#22d3ee; --money:#fbbf24; --good:#34d399; --bad:#fb7185;
 --mono:"IBM Plex Mono",ui-monospace,Menlo,monospace;
 --disp:"Oswald","Arial Narrow",system-ui,sans-serif;
 --body:"IBM Plex Sans",system-ui,-apple-system,sans-serif;
}}
*{{box-sizing:border-box}}
body{{background:var(--ground);color:var(--ink);font-family:var(--body);line-height:1.5;
 padding-inline:20px;padding-block:0;margin:0}}
.wrap{{max-width:1180px;margin:0 auto;padding-block:34px 60px}}
h1{{font-family:var(--disp);font-weight:600;font-size:clamp(30px,5vw,46px);letter-spacing:.01em;
 text-transform:uppercase;margin:0;text-wrap:balance;line-height:1.04}}
.kicker{{font-family:var(--mono);font-size:11px;letter-spacing:.28em;text-transform:uppercase;
 color:var(--accent);margin:0 0 10px}}
.sub{{color:var(--ink-2);max-width:66ch;margin:12px 0 0;font-size:14px}}
.sub b{{color:var(--ink);font-weight:600}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:1px;
 background:var(--line-soft);border:1px solid var(--line);margin:26px 0 34px}}
.stat{{background:var(--panel);padding:14px 16px}}
.stat .v{{font-family:var(--mono);font-size:22px;font-weight:600;color:var(--ink);
 font-variant-numeric:tabular-nums;line-height:1.1}}
.stat .v.acc{{color:var(--money)}}
.stat .l{{font-family:var(--mono);font-size:9.5px;letter-spacing:.17em;text-transform:uppercase;
 color:var(--ink-3);margin-top:6px}}
h2{{font-family:var(--disp);font-weight:600;font-size:19px;text-transform:uppercase;
 letter-spacing:.06em;margin:0 0 3px}}
.note{{color:var(--ink-3);font-size:12.5px;margin:0 0 14px}}
.scroll{{overflow-x:auto;border:1px solid var(--line);background:var(--panel)}}
table{{border-collapse:collapse;width:100%;min-width:860px}}
thead th{{font-family:var(--mono);font-size:9.5px;letter-spacing:.15em;text-transform:uppercase;
 color:var(--ink-3);font-weight:400;text-align:right;padding:11px 9px;
 border-bottom:1px solid var(--line);white-space:nowrap;background:var(--panel2)}}
thead th:nth-child(2){{text-align:left}}
tbody td{{padding:9px;border-bottom:1px solid var(--line-soft);font-size:13px;text-align:right;
 vertical-align:middle}}
tbody tr:last-child td{{border-bottom:0}}
tbody tr:hover td{{background:#131a27}}
.rank{{font-family:var(--mono);color:var(--ink-3);font-size:11px;width:30px;text-align:right}}
.team{{text-align:left;display:flex;align-items:center;gap:9px;min-width:236px}}
.stripe{{width:3px;height:20px;border-radius:2px;flex:0 0 3px}}
.tname{{font-weight:600;font-size:13px;white-space:nowrap}}
.tabbr{{font-family:var(--mono);font-size:9.5px;color:var(--ink-3);letter-spacing:.1em}}
.num{{font-family:var(--mono);font-variant-numeric:tabular-nums}}
.strong{{color:var(--accent);font-weight:600;font-size:14px}}
.dim{{color:var(--ink-3)}}
.purse{{min-width:132px}}
.bar{{height:3px;background:#1a2334;border-radius:2px;overflow:hidden;margin-bottom:5px}}
.bar i{{display:block;height:100%;border-radius:2px}}
.spent{{color:var(--money);font-size:12px}}
.ok{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--good)}}
.bad{{font-family:var(--mono);font-size:9.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--bad)}}
.split{{margin-top:40px}}
.tops{{list-style:none;margin:0;padding:0;border:1px solid var(--line);background:var(--panel)}}
.tops li{{display:flex;align-items:center;gap:12px;padding:9px 14px;border-bottom:1px solid var(--line-soft)}}
.tops li:last-child{{border-bottom:0}}
.tp{{font-family:var(--mono);color:var(--money);font-weight:600;width:60px;font-variant-numeric:tabular-nums}}
.tn{{flex:1;font-size:13px;font-weight:600}}
.tt{{font-family:var(--mono);font-size:10px;letter-spacing:.1em;font-weight:600}}
.tr{{font-family:var(--mono);font-size:10px;color:var(--ink-3);width:42px;text-align:right}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(330px,1fr));gap:16px;margin-top:16px}}
.squad{{border:1px solid var(--line);background:var(--panel);border-top:2px solid var(--team)}}
.squad header{{padding:13px 15px 11px;border-bottom:1px solid var(--line)}}
.squad h3{{font-family:var(--disp);font-weight:600;font-size:15px;text-transform:uppercase;
 letter-spacing:.04em;margin:0;color:var(--team)}}
.meta{{font-family:var(--mono);font-size:10px;color:var(--ink-3);margin:5px 0 0;line-height:1.7}}
.meta b{{color:var(--ink-2);font-weight:600}}
.plist{{list-style:none;margin:0;padding:0}}
.plist li{{display:grid;grid-template-columns:1fr 42px 26px 48px;gap:8px;align-items:center;
 padding:5px 15px;border-bottom:1px solid var(--line-soft);font-size:12px}}
.plist li:last-child{{border-bottom:0}}
.plist li.xi{{background:#121a28}}
.plist li.xi .pn{{color:var(--ink);font-weight:600}}
.pn{{color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.os{{color:var(--accent);font-size:9px;margin-left:5px;opacity:.75}}
.pr{{font-family:var(--mono);font-size:9px;color:var(--ink-3);letter-spacing:.06em;text-transform:uppercase}}
.pv{{font-family:var(--mono);font-size:10px;color:var(--ink-3);text-align:right;font-variant-numeric:tabular-nums}}
.pp{{font-family:var(--mono);font-size:11px;color:var(--money);text-align:right;font-variant-numeric:tabular-nums}}
.legend{{font-family:var(--mono);font-size:10.5px;color:var(--ink-3);margin:12px 0 0;line-height:1.9}}
.legend b{{color:var(--ink-2);font-weight:600}}
footer{{margin-top:46px;padding-top:18px;border-top:1px solid var(--line);
 font-family:var(--mono);font-size:10.5px;color:var(--ink-3);line-height:1.9}}
@media (max-width:560px){{
 .plist li{{grid-template-columns:1fr 38px 40px}}
 .pv{{display:none}}
}}
</style>

<div class="wrap">
<p class="kicker">Simulation &middot; all ten seats AI &middot; seed {seed}</p>
<h1>IPL 2026 Auction Sheet</h1>
<p class="sub">One complete auction played through the live game engine &mdash; the same code the browser talks to, so the head-to-head duel rule, the going-once/twice/thrice count, per-lot bid noise and set shuffling all applied. Every franchise was driven by the trained PPO policy. Squads ranked by <b>XI strength</b>: the summed value score of the best legal playing eleven each squad can field.</p>

<div class="stats">
<div class="stat"><div class="v">{lots}</div><div class="l">Lots</div></div>
<div class="stat"><div class="v">{sold}</div><div class="l">Players sold</div></div>
<div class="stat"><div class="v acc">{spent:.2f}</div><div class="l">Crore spent</div></div>
<div class="stat"><div class="v">{used:.1f}%</div><div class="l">Purse used</div></div>
<div class="stat"><div class="v">{legal}/10</div><div class="l">Legal XI</div></div>
</div>

<h2>Standings</h2>
<p class="note">Ranked by XI strength. Purse bar shows spend against the 125 Cr cap.</p>
<div class="scroll"><table>
<thead><tr><th></th><th>Franchise</th><th>XI</th><th>Squad</th><th>Spent (Cr)</th><th>Left</th>
<th>Bat</th><th>WK</th><th>All-r</th><th>Pace</th><th>Spin</th><th>Os</th><th>Status</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="legend"><b>Os</b> &mdash; overseas players, capped at 8 per squad. <b>Pace / Spin</b> &mdash; specialist bowlers only, split by bowling style in the source data; all-rounders who bowl are counted under All-r.</p>

<div class="split"><h2>Biggest cheques</h2>
<p class="note">Top eight prices of the auction.</p>
<ol class="tops">{tops}</ol></div>

<h2 style="margin-top:40px">Squads</h2>
<p class="note">Every signing, highest price first. Highlighted players make that squad's best legal XI. &#9992; marks an overseas player.</p>
<div class="grid">{panels}</div>

<footer>Generated from a single seeded playthrough (seed {seed}) of backend/game/auction_room.py.<br>
Value score is the model's 0&ndash;100 career rating; price in Crore. Purse 125 Cr, squad target 20, maximum 8 overseas.</footer>
</div>
"""


if __name__ == "__main__":
    path = build(int(sys.argv[1]) if len(sys.argv) > 1 else 2026)
    print(f"wrote {path}")
