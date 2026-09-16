# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

IPL Auction Simulator — the user plays one IPL franchise and bids against 9 AI-controlled
franchises to build a 20-player squad within a 100 Crore budget.

The repo is transitioning from a frontend-only prototype to a two-layer architecture:
- `src/` — React frontend (existing, being kept as the presentation layer)
- `backend/` — Python backend (new, in early scaffolding). Intended to own all auction game
  logic, AI franchise agent behavior, and ML-based player valuation, replacing the
  in-browser simulation currently in `src/App.tsx`. Communication is planned over
  WebSocket (real-time bidding events) with REST for one-off actions (start game, load
  CSV, reset). As of now `backend/` only has FastAPI + Uvicorn installed and a placeholder
  `main.py` — no engine, agents, or ML code exist yet.

When working on auction logic, check whether the intent is to extend the existing
frontend simulation (`src/App.tsx`) or to build the equivalent in `backend/` — do not
assume; ask if unclear.

## Commands

### Frontend (`/` — run from repo root)
- `npm run dev` — start Vite dev server on port 3000 (bound to 0.0.0.0)
- `npm run build` — production build
- `npm run preview` — preview a production build
- `npm run lint` — type-check only (`tsc --noEmit`); there is no separate lint config
- `npm run clean` — remove `dist/` and `server.js`
- No test suite exists yet.

### Backend (`backend/`)
- `uv venv` — create the virtualenv (`.venv`), already done
- `uv add <package>` — add a dependency (updates `pyproject.toml` and `uv.lock`)
- `uv run <script>` — run a script inside the project's venv without manual activation
- No app entrypoint, tests, or lint config exist yet beyond the placeholder `main.py`.

## Frontend architecture (`src/App.tsx`)

The entire game currently lives in one component, `src/App.tsx` (~2000 lines), which owns
all state and logic. Supporting pieces:
- `src/types.ts` — core domain types: `Player`, `Team`, `AIStrategy`, `PlayerBidInfo`, `BiddingLog`
- `src/data/defaultPlayers.ts`, `src/data/defaultTeams.ts` — built-in player pool and the
  10 franchises, each with a distinct `AIStrategy` (role weights, max bid, target squad
  composition, ideal budget split per role)
- `src/components/` — presentational components (`CsvUploader`, `Leaderboard`,
  `BiddingLog`, `SquadModal`, `Confetti`); custom player data can be imported via CSV
  instead of using the defaults

### Game phase state machine
`SETUP → SET_SELECTION → AUCTION_STAGE → NOMINATION → BOOST_ROUND → COMPLETED`

- **SETUP** — user picks their franchise
- **SET_SELECTION** — choose a player category/set to auction next (Marquee, Batsman,
  Bowler, etc., or custom CSV-defined sets — sorted by a priority parser in `getUniqueSets`)
- **AUCTION_STAGE** — players go under the hammer one at a time; bid increments come from
  `getNextBid` (+0.20 Cr below 2 Cr, +0.50 Cr below 5 Cr, +1 Cr above)
- **NOMINATION / BOOST_ROUND** — accelerated round re-auctioning unsold players at half
  base price so every team finishes with exactly 20 players
- **COMPLETED** — leaderboard/stats/awards screen

### AI bidding logic
`calculateAIValuation` (in `App.tsx`) is the core of the simulation: each AI franchise
computes how much it's willing to pay for a player from role-preference weight, a
rating factor, squad-need urgency (empty roles bid more aggressively), budget aggression
relative to that strategy's ideal per-role spend, a wallet-size multiplier, and a
per-team `absoluteMaxBid` cap (plus a special-cased conservative bid cap for Punjab).
Budget-safety-margin checks (reserving 0.20 Cr per remaining empty slot) and an 8-foreign-
player roster cap are enforced for both AI teams and the human player. All AI teams bid
automatically inside the `useEffect` game loop each tick if their valuation clears the
next bid increment.

This valuation function is the piece the Python backend's ML models / agents are meant
to eventually replace or supersede — see project overview above.
