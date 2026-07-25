"""
Manual test client for Phase 2 - plays two "players" through create_room /
join_room / leave_room against a REAL running server, so you can see the
actual events fire over the wire.

Usage:
    1. In one terminal: uvicorn main:asgi_app --reload
    2. In another terminal (with the venv activated): python test_socket_flow.py
"""
import socketio
import time

SERVER_URL = "http://127.0.0.1:8000"

host = socketio.Client()
guest = socketio.Client()

room_code_holder = {}


@host.on("room_created")
def on_room_created(data):
    print(f"[HOST] room_created  -> {data}")
    room_code_holder["code"] = data["room_code"]


@host.on("player_joined")
def on_host_sees_join(data):
    print(f"[HOST] player_joined -> {data}")


@host.on("player_left")
def on_host_sees_leave(data):
    print(f"[HOST] player_left   -> {data}")


@host.on("error")
def on_host_error(data):
    print(f"[HOST] error         -> {data}")


@guest.on("player_joined")
def on_guest_joined(data):
    print(f"[GUEST] player_joined -> {data}")


@guest.on("error")
def on_guest_error(data):
    print(f"[GUEST] error         -> {data}")


print("Connecting host...")
host.connect(SERVER_URL)

print("Host creating room...")
host.emit("create_room", {
    "player_id": "player-host-001",
    "username": "Raghav",
    "avatar_config": {"hair": "short", "skin_tone": "#F1C27D"},
})
time.sleep(1)  # give the server a moment to respond

room_code = room_code_holder.get("code")
if not room_code:
    print("Did not receive a room code - is the server running? Check Terminal 1.")
    host.disconnect()
    raise SystemExit(1)

print(f"\nGot room code: {room_code}\n")

print("Connecting guest...")
guest.connect(SERVER_URL)
time.sleep(1)

print("Guest joining room...")
guest.emit("join_room", {
    "room_code": room_code,
    "player_id": "player-guest-001",
    "username": "Ananya",
    "avatar_config": {"hair": "long"},
})
time.sleep(2)

print("\nGuest leaving room...")
guest.emit("leave_room", {"room_code": room_code, "player_id": "player-guest-001"})
time.sleep(2)

print("\nDone. Disconnecting both.")
guest.disconnect()
host.disconnect()
