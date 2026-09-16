# IPL Auction Simulator

Play one IPL franchise and bid against 9 AI-controlled franchises in a live,
real-time player auction. The AI teams are driven by a PPO reinforcement-learning
policy trained against real historical team behaviour, player prices come from
an XGBoost fair-value model trained on real ball-by-ball career data, and the
auctioneer speaks with a neural (Piper) voice.

## What's in this project

- **A real-time auction room** (React) — a 2.5D room with team desks, a
  head-to-head bidding duel, a going-once/twice/thrice hammer count, and
  live/fast/instant playback speeds.
- **A trained AI opponent for every franchise** (Python / PyTorch via
  Stable-Baselines3) — one shared, team-conditioned PPO policy that values
  players the way each real franchise's history suggests it would.
- **A fair-price model** (XGBoost) trained on real player career data, which
  every AI team's willingness to bid is measured against.
- **A neural auctioneer voice** (Piper, offline TTS) that reads out every
  player, every bid, and the hammer falling.
- **A real-time backend** (FastAPI + WebSocket) running the actual auction
  rules — squad legality, overseas caps, budget, the boost round for unsold
  players — shared identically between training and the live game.

## Project structure

```
ipl_auction_sim/
├── src/                      # React frontend
│   ├── App.tsx                 # Main game screen and state machine
│   ├── components/              # AuctionRoom, Leaderboard, SquadModal, ...
│   ├── hooks/                   # WebSocket client, auction event playback
│   └── lib/                     # Voice (TTS) and sound-effect helpers
│
├── backend/                  # Python backend
│   ├── main.py                  # FastAPI app + WebSocket endpoint
│   ├── game/                    # Live auction engine (rules, bidding, model loading)
│   ├── rl/                      # PPO training code, the trained model, FINDINGS.md
│   ├── data_pipeline/            # Builds team_profiles.json from historical data
│   ├── reports/                  # Tools to run and evaluate a full mock auction
│   └── voices/                   # Piper voice model + generated speech cache
│
└── data/                     # Player pool, historical team data
```

## Prerequisites

- **Node.js** 18+ (tested on 24)
- **Python** 3.12+
- **[uv](https://docs.astral.sh/uv/)** — Python package manager used by the backend

## Setup

### 1. Clone the repository

```bash
git clone git@github.com:arunak1998/ipl_auction_sim.git
cd ipl_auction_sim
```

### 2. Install frontend packages

From the repository root:

```bash
npm install
```

### 3. Install backend packages

```bash
cd backend
uv sync
cd ..
```

This creates `backend/.venv` with every backend dependency (FastAPI, PyTorch,
Stable-Baselines3, XGBoost, Piper TTS, etc.) pinned to `backend/uv.lock`.

## Running the app

Two servers, **backend first, then frontend** — the frontend connects to the
backend over WebSocket on startup and needs it already running.

### 4. Start the backend server

```bash
cd backend
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

Wait until it prints `Application startup complete` — it loads the trained
model and the full player pool, which takes a few seconds. Leave this
running in its own terminal.

### 5. Start the frontend server

In a **new terminal**, from the repository root:

```bash
npm run dev
```

Open the printed URL — normally **http://localhost:3000**.

That's it: pick your franchise and start the auction.

## Notes

- The frontend expects the backend at `ws://localhost:8000/ws/auction` by
  default. To point it elsewhere, set `VITE_BACKEND_WS_URL` before running
  `npm run dev`.
- If you edit backend or frontend code while a server is running, restart
  that server to pick up the change — `npm run dev`'s hot-reload does not
  reliably pick up file changes on all filesystems (notably WSL's `/mnt/c`).
- The trained model and how it was arrived at — including which experiments
  were tried and rejected — are documented in `backend/rl/FINDINGS.md`.
