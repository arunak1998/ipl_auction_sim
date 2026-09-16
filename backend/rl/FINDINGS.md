# Identity-feature experiments — closed, 2026-09-15

Two attempts at giving the trained policy stronger per-franchise identity
were tried, measured, and **rejected**. The live model
(`ppo_auction_mdp_v5.zip`, backed up at
`rl/baseline/ppo_auction_mdp_v5_BASELINE.zip`) is the pre-experiment
baseline. Neither experiment's weights are kept on disk — this file plus
the measured numbers is the record.

## 1. Player-side pace/spin (`is_pace` / `is_spin` observation features)

**Rejected: the identity gain was a market-collapse artefact, not real.**

The baseline observation never told the policy whether a bowler was pace
or spin (verified: flipping a player's `bowler_subtype` changed 0 of the
45 baseline observation dimensions), even though the team block had
carried each franchise's real historical pace/spin split since the v4
data work. Adding the two player-side features and retraining moved the
**spinner ratio** (spin-leaning teams' spin-bowler share ÷ pace-leaning
teams') from baseline's 1.11 to **2.83** — a promising, promoted result.

Full-auction verification then showed the market had collapsed: purse
utilization dropped from ~90% to **22%**, and Virat Kohli — the highest
fair-price player in the pool, 26–27 Cr on baseline in every seed — sold
for **2.00 Cr (base price) three times in a row**. The policy had learned
a "snipe only the elite few, ignore everyone else" equilibrium: elite-tier
bidding stayed healthy, but the good tier (value_score 50–64) died
entirely (0 bids/lot, 100% zero-bid lots).

Two fixes were tried, in sequence, each measured against a **tiered
market-health gate** (`reports/gate_market_health.py`) rather than the
spinner ratio alone:

- A `1.0`-phase added to the training curriculum (every seat = trained
  policy, the actual deployment condition, never trained before —
  0.75 was the prior ceiling). One 200k-step phase alone took the good
  tier from 100% zero-bid to 82.4%, purse from 22% to 56%.
- Extended to a full 8-phase, 1.8M-step curriculum (0.90 ramp step +
  400k final phase at 1.0). Good tier reached 77.3% zero-bid, purse 74%.
  **Still failed the pre-registered gate** (good-tier zero-bid rate
  needed to clear <50%).

Critically, as the market recovered, **the spinner ratio walked back
down with it**: 2.83 → 5.20 (unstable across seeds:
`[3.0, 1.84, 10.75]`) → **1.21**, converging on baseline's own 1.11.
The identity gain never existed independent of the collapse that
produced it.

**Kept, permanently:** the `1.0` curriculum phase in
`rl/train_mdp_v5.py`'s `CURRICULUM` — a real, independent fix for a
real train/deploy gap (elite-tier bids/lot went 0.66 → 13.73 on that
phase alone). The tiered market-health gate itself, which caught its
own aggregation bug (an early "overall bids/lot" pass criterion failed
*baseline*) and caught the 5.20 spinner-ratio headline as noise before
it could be mistaken for a second win.

## 2. Team-side star-spend features (`team_variant="star_spend"`)

**Rejected: measured weak on its own terms, and the source data can't
support more than that.**

Swapped 4 features from `data/team_history_features.json`
(`star_spend_bowler_pct`, `star_spend_allrounder_pct`,
`star_spend_batter_pct`, `star_top_price_cr`) into the 8-feature team
block, replacing the 4 weakest of the existing set by a measured
separation test. Retrained in isolation from the pace/spin change (so
the two effects wouldn't be conflated).

```
                     baseline -> star_spend
top-price ratio        0.79  ->  1.05   (fixes an inversion, no real lift)
bowler-spend ratio      1.02  ->  1.12   (small, unstable)
```

Not pursued further: the underlying historical data is thin (673 top
transactions total; GT and LSG on small samples; no total-spend field
to build a real concentration measure from). A different eviction set
would not fix a data problem.

**The code stays, dormant.** `team_variant` in `build_observation`
(`rl/auction_mdp.py`) defaults to `"baseline"` everywhere, including the
live game — this is documented, working, opt-in infrastructure for a
*better-sourced* future attempt, not dead code to rip out.

## 3. Open, unresolved: DC/GT purse-left clustering

Not an identity-feature question — found while re-verifying baseline
after the above. **Real, reproducible, not yet understood.**

Across 10 fresh seeds, DC and GT land in the top-2 biggest
purse-underspenders 5/10 times each (chance would predict ~2/10); MI,
RCB, SRH and RR land there 0/10 times. Investigated and ruled out:

- **Not a valuation gap.** DC's own per-lot mean ceiling-to-fair ratio
  was the *highest* of the 9 AI teams; its zero-ceiling rate (72.1%)
  sits mid-pack.
- **Not a late-auction/pacing effect.** Every team, both clusters,
  follows the identical zero-rate decay curve across the auction
  (~42% early → ~79% mid → ~95% late) — a property of the auction
  running out of good players, not of team identity.
- **Not a marquee-lot valuation gap either.** On the 45 most expensive
  lots (top 15/seed × 3 seeds), all 8 teams behave statistically
  identically (ceiling ratio 0.88–0.94 for every team, near-zero
  zero-rate for every team).

One static feature interaction cleanly separates the two clusters —
`aggression_factor × pace_Pace` (every chronic underspender scores
above 0.596; every never-underspender scores below 0.568, no overlap,
n=4 each side) — but it predicts *which teams* end up underspending
without explaining *where in behaviour* the effect lives, since neither
resolution checked above shows a behavioural difference. Candidate
remaining mechanism: how close multi-way duels resolve under
headroom-weighted random tie-breaking + per-lot bid noise, which
wouldn't show up in any average across lots that aren't close
multi-way fights. Not yet investigated.

**Tracked, not blocking:** `reports/gate_market_health.py` now reports
a non-blocking purse-left rank distribution per team across N seeds on
every run, so a future model's over/underspend pattern has a number to
compare against without re-running this investigation.
