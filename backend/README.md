# Backend

FastAPI + WebSocket server for the IPL Auction Simulator's live auction
engine, AI franchise models, and price prediction.

**Full setup and run instructions live in the [repository root
README](../README.md)** — this file only covers backend-specific detail.

## Run directly

```bash
uv sync
uv run uvicorn main:app --host 0.0.0.0 --port 8000
```

## Layout

- `main.py` — FastAPI app and the `/ws/auction` WebSocket endpoint
- `game/` — the live auction engine: bidding rules, squad legality,
  model loading (`game/model_registry.py`), the auction room itself
  (`game/auction_room.py`)
- `rl/` — PPO training code (`train_mdp_v5.py`), the environment
  (`auction_mdp.py`), the trained model (`ppo_auction_mdp_v5.zip`), and
  **`FINDINGS.md`** — what was tried on top of the shipped model, measured,
  and rejected, with the numbers
- `data_pipeline/` — builds `team_profiles.json` (each franchise's real
  historical bidding behaviour) from the raw historical auction data
- `reports/` — tools to run a full 10-team AI-only auction
  (`play_full_auction.py`), render it as a report (`build_report.py`), and
  gate a candidate model's market health before ever promoting it
  (`gate_market_health.py`)
- `voices/` — the Piper TTS voice model and its generated-speech cache

## Tests / evaluation

There's no unit test suite. To sanity-check a change, run a full mock
auction and inspect the result:

```bash
uv run python reports/play_full_auction.py 2026
uv run python reports/build_report.py 2026
```

And before ever promoting a new candidate model to live, gate it:

```bash
uv run python reports/gate_market_health.py <model-tag> 3
```
