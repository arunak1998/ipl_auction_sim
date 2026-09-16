from fastapi import FastAPI, Query, Response, WebSocket, WebSocketDisconnect

from game import tts
from fastapi.middleware.cors import CORSMiddleware

from game.auction_room import AuctionRoom
from game.model_registry import TEAM_IDS, ModelRegistry

app = FastAPI(title="IPL Auction Simulator Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Loaded once at server startup (loading 10 PPO models per connection would
# be slow and wasteful) -- inference (model.predict) doesn't mutate a model,
# so sharing this one instance across all connections is safe.
model_registry = ModelRegistry()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/teams")
def teams():
    """Lets the frontend populate its team-selection screen without
    hardcoding the id list twice."""
    return {
        "teams": [
            {"team_id": tid, "model_version": model_registry.version_of(tid)}
            for tid in TEAM_IDS
        ]
    }


@app.get("/tts")
def tts_line(f: list[str] = Query(default=[])):
    """Assemble one auctioneer line from pre-generated fragments.

    Takes fragments rather than a sentence on purpose: every fragment is
    already cached as PCM, so this is byte concatenation rather than
    synthesis, and stays fast enough to narrate a live bidding war (see
    game/tts.py). Returns 404 when Piper or the voice model is absent, which
    the frontend treats as "fall back to the browser voice".
    """
    wav = tts.speak_wav(f) if f else None
    if wav is None:
        return Response(status_code=404)
    return Response(
        content=wav,
        media_type="audio/wav",
        # Same fragments produce the same bytes forever -- let the browser
        # keep them so a repeated call never touches the server again.
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.websocket("/ws/auction")
async def auction_socket(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "CONNECTED", "payload": {"message": "connected to auction engine"}})

    room: AuctionRoom | None = None

    def state_response(msg_type: str, events: list[dict]) -> dict:
        return {"type": msg_type, "payload": {"events": events, "state": room.get_state_snapshot()}}

    try:
        while True:
            message = await websocket.receive_json()
            msg_type = message.get("type")
            payload = message.get("payload") or {}

            if msg_type == "START_AUCTION":
                team_id = payload.get("team_id")
                if team_id not in TEAM_IDS:
                    await websocket.send_json({"type": "ERROR", "payload": {"message": f"Unknown team_id: {team_id}"}})
                    continue
                room = AuctionRoom(human_team_id=team_id, model_registry=model_registry)
                await websocket.send_json(state_response("AUCTION_STARTED", []))

            elif room is None:
                await websocket.send_json({"type": "ERROR", "payload": {"message": "No auction in progress -- send START_AUCTION first."}})

            elif msg_type == "OPEN_SET":
                events = room.open_set(payload.get("set_name"))
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type in ("PLACE_BID", "PASS", "RESOLVE_LOT"):
                action = {"PLACE_BID": "BID", "PASS": "PASS", "RESOLVE_LOT": "RESOLVE"}[msg_type]
                events = room.place_human_action(action)
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type == "AI_TICK":
                # One beat of the frontend-driven auction clock. `final_call`
                # is set while the hammer is coming down, which is the only
                # time a team outside the duel may cut in.
                events = room.ai_tick(allow_new_entrant=bool(payload.get("final_call")))
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type == "SETTLE_LOT":
                events = room.settle_lot()
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type == "SIT_OUT":
                events = room.sit_out()
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type == "SET_AUTO_BID":
                limit = payload.get("limit_cr")
                events = room.set_auto_bid(float(limit) if limit is not None else None)
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type == "TOGGLE_NOMINATION":
                events = room.toggle_nomination(payload.get("player_id"))
                await websocket.send_json(state_response("UPDATE", events))

            elif msg_type == "LAUNCH_BOOST_ROUND":
                events = room.launch_boost_round()
                await websocket.send_json(state_response("UPDATE", events))

            else:
                await websocket.send_json({"type": "ERROR", "payload": {"message": f"Unknown message type: {msg_type}"}})

    except WebSocketDisconnect:
        pass
