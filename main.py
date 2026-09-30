import asyncio
import os
import time
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


# ============================================================
# CONFIG
# ============================================================

LAB_SECRET = os.getenv("LAB_SECRET", "LAB-123456")

PC_DEVICE_ID = "pc-main"

STALE_TIMEOUT = 30


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="JARVIS Cloud Relay",
    version="1.0.0",
)


# ============================================================
# DEVICE REGISTRY
# ============================================================

devices: Dict[str, dict] = {}

connections: Dict[str, WebSocket] = {}

device_info: Dict[str, dict] = {}


# ============================================================
# LOCK
# ============================================================

registry_lock = asyncio.Lock()


# ============================================================
# TIME
# ============================================================

def now() -> float:
    return time.time()


# ============================================================
# STATUS
# ============================================================

def is_device_online(device_id: str) -> bool:
    ws = connections.get(device_id)

    if ws is None:
        return False

    device = devices.get(device_id)

    if device is None:
        return False

    last_seen = device.get("last_seen", 0)

    if now() - last_seen > STALE_TIMEOUT:
        return False

    return True


def update_device_status(device_id: str):
    if device_id not in devices:
        return

    devices[device_id]["status"] = (
        "online"
        if is_device_online(device_id)
        else "offline"
    )


# ============================================================
# DEVICE REGISTRATION
# ============================================================

async def register_device(
    device_id: str,
    device_type: str,
    websocket: WebSocket,
):
    async with registry_lock:

        connections[device_id] = websocket

        if device_id not in devices:
            devices[device_id] = {
                "device_id": device_id,
                "device_type": device_type,
                "status": "online",
                "connected_at": now(),
                "last_seen": now(),
            }
        else:
            devices[device_id]["device_type"] = device_type
            devices[device_id]["status"] = "online"
            devices[device_id]["last_seen"] = now()

        if device_id not in device_info:
            device_info[device_id] = {}


def unregister_device(device_id: str, websocket: WebSocket):
    current = connections.get(device_id)

    if current is websocket:
        connections.pop(device_id, None)

        if device_id in devices:
            devices[device_id]["status"] = "offline"
            devices[device_id]["last_seen"] = now()


def touch_device(device_id: str):
    if device_id in devices:
        devices[device_id]["last_seen"] = now()
        devices[device_id]["status"] = "online"


# ============================================================
# SEND JSON
# ============================================================

async def send_json(
    websocket: Optional[WebSocket],
    data: dict,
) -> bool:

    if websocket is None:
        return False

    try:
        await websocket.send_json(data)
        return True

    except Exception:
        return False


# ============================================================
# FIND DEVICE
# ============================================================

def get_device_socket(device_id: str) -> Optional[WebSocket]:
    websocket = connections.get(device_id)

    if websocket is None:
        return None

    if not is_device_online(device_id):
        return None

    return websocket


# ============================================================
# DEVICE LIST
# ============================================================

def build_device_list():

    result = []

    for device_id, device in devices.items():

        update_device_status(device_id)

        result.append(
            {
                "device_id": device_id,
                "device_type": device.get(
                    "device_type",
                    "unknown",
                ),
                "status": device.get(
                    "status",
                    "offline",
                ),
                "connected_at": device.get(
                    "connected_at"
                ),
                "last_seen": device.get(
                    "last_seen"
                ),
                "info": device_info.get(
                    device_id,
                    {},
                ),
            }
        )

    return result


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "service": "JARVIS Cloud Relay",
        "status": "running",
        "version": "1.0.0",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    online_count = 0

    for device_id in devices:
        update_device_status(device_id)

        if devices[device_id].get("status") == "online":
            online_count += 1

    return {
        "status": "healthy",
        "devices": len(devices),
        "online": online_count,
    }


# ============================================================
# DEVICES
# ============================================================

@app.get("/devices")
async def get_devices():

    return {
        "devices": build_device_list()
    }


# ============================================================
# WEBSOCKET
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    current_device_id: Optional[str] = None
    current_device_type: Optional[str] = None

    try:

        while True:

            message = await websocket.receive()

            # =================================================
            # TEXT MESSAGE
            # =================================================

            if message.get("text") is not None:

                try:
                    data = __import__("json").loads(
                        message["text"]
                    )

                except Exception:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Invalid JSON",
                        },
                    )

                    continue

                message_type = data.get("type")

                # =============================================
                # PAIR REQUEST
                # =============================================

                if message_type == "pair_request":

                    secret = data.get("secret")

                    if secret != LAB_SECRET:

                        await send_json(
                            websocket,
                            {
                                "type": "pair_response",
                                "success": False,
                                "message": "Invalid pairing secret",
                            },
                        )

                        continue

                    device_id = data.get("device_id")

                    device_type = data.get(
                        "device_type",
                        "android",
                    )

                    if not device_id:

                        await send_json(
                            websocket,
                            {
                                "type": "pair_response",
                                "success": False,
                                "message": "Missing device_id",
                            },
                        )

                        continue

                    current_device_id = device_id
                    current_device_type = device_type

                    await register_device(
                        device_id,
                        device_type,
                        websocket,
                    )

                    await send_json(
                        websocket,
                        {
                            "type": "pair_response",
                            "success": True,
                            "device_id": device_id,
                            "message": "Device paired successfully",
                        },
                    )

                    print(
                        f"[PAIR] {device_id} "
                        f"({device_type}) connected"
                    )

                    continue

                # =============================================
                # PC REGISTER
                # =============================================

                if message_type == "pc_register":

                    secret = data.get("secret")

                    if secret != LAB_SECRET:

                        await send_json(
                            websocket,
                            {
                                "type": "pc_register_response",
                                "success": False,
                                "message": "Invalid secret",
                            },
                        )

                        continue

                    device_id = data.get(
                        "device_id",
                        PC_DEVICE_ID,
                    )

                    device_type = data.get(
                        "device_type",
                        "pc",
                    )

                    current_device_id = device_id
                    current_device_type = device_type

                    await register_device(
                        device_id,
                        device_type,
                        websocket,
                    )

                    await send_json(
                        websocket,
                        {
                            "type": "pc_register_response",
                            "success": True,
                            "device_id": device_id,
                            "message": "PC registered successfully",
                        },
                    )

                    print(
                        f"[PC] {device_id} connected"
                    )

                    continue

                # =============================================
                # DEVICE MUST BE REGISTERED
                # =============================================

                if current_device_id is None:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Device not registered",
                        },
                    )

                    continue

                touch_device(current_device_id)

                # =============================================
                # HEARTBEAT
                # =============================================

                if message_type == "heartbeat":

                    await send_json(
                        websocket,
                        {
                            "type": "heartbeat_response",
                            "timestamp": now(),
                        },
                    )

                    continue

                # =============================================
                # PING
                # =============================================

                if message_type == "ping":

                    await send_json(
                        websocket,
                        {
                            "type": "pong",
                            "timestamp": now(),
                        },
                    )

                    continue

                # =============================================
                # DEVICE INFO
                # =============================================

                if message_type == "device_info":

                    info = data.get("info", {})

                    if isinstance(info, dict):
                        device_info[current_device_id] = info

                    await send_json(
                        websocket,
                        {
                            "type": "device_info_response",
                            "success": True,
                            "device_id": current_device_id,
                            "info": device_info.get(
                                current_device_id,
                                {},
                            ),
                        },
                    )

                    continue

                # =============================================
                # LIST DEVICES
                # =============================================

                if message_type == "list_devices":

                    await send_json(
                        websocket,
                        {
                            "type": "devices",
                            "devices": build_device_list(),
                        },
                    )

                    continue

                # =============================================
                # COMMAND
                # =============================================

                if message_type == "command":

                    target_device_id = data.get(
                        "device_id"
                    )

                    if not target_device_id:

                        target_device_id = PC_DEVICE_ID

                    target_socket = get_device_socket(
                        target_device_id
                    )

                    if target_socket is None:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": data.get(
                                    "command_id"
                                ),
                                "message": (
                                    f"Device "
                                    f"{target_device_id} "
                                    f"is offline"
                                ),
                            },
                        )

                        continue

                    command = {
                        "type": "command",
                        "device_id": target_device_id,
                        "command_id": data.get(
                            "command_id"
                        ),
                        "command": data.get(
                            "command"
                        ),
                        "args": data.get(
                            "args",
                            {},
                        ),
                        "source_device_id": (
                            current_device_id
                        ),
                    }

                    sent = await send_json(
                        target_socket,
                        command,
                    )

                    if not sent:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": data.get(
                                    "command_id"
                                ),
                                "message": (
                                    "Failed to send "
                                    "command"
                                ),
                            },
                        )

                    continue

                # =============================================
                # COMMAND RESPONSE
                # =============================================

                if message_type == "command_response":

                    source_device_id = data.get(
                        "source_device_id"
                    )

                    if not source_device_id:

                        source_device_id = data.get(
                            "target_device_id"
                        )

                    if not source_device_id:

                        source_device_id = PC_DEVICE_ID

                    target_socket = get_device_socket(
                        source_device_id
                    )

                    if target_socket:

                        response = dict(data)

                        response[
                            "response_device_id"
                        ] = current_device_id

                        await send_json(
                            target_socket,
                            response,
                        )

                    continue

                # =============================================
                # UNKNOWN MESSAGE
                # =============================================

                await send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": (
                            f"Unknown message type: "
                            f"{message_type}"
                        ),
                    },
                )

            # =================================================
            # BINARY MESSAGE
            # =================================================

            elif message.get("bytes") is not None:

                # This server intentionally does not implement
                # arbitrary remote media capture/streaming.
                #
                # Binary messages are rejected unless the
                # application protocol is explicitly extended
                # with a consent-based feature.

                if current_device_id:

                    touch_device(current_device_id)

                await send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": (
                            "Binary payloads are not enabled "
                            "by this relay"
                        ),
                    },
                )

    except WebSocketDisconnect:

        print(
            f"[DISCONNECT] "
            f"{current_device_id or 'unknown'}"
        )

    except Exception as exc:

        print(
            f"[WEBSOCKET ERROR] "
            f"{current_device_id or 'unknown'}: "
            f"{exc}"
        )

    finally:

        if current_device_id:

            unregister_device(
                current_device_id,
                websocket,
            )

            print(
                f"[OFFLINE] {current_device_id}"
            )


# ============================================================
# BACKGROUND STATUS CLEANUP
# ============================================================

async def status_cleanup_loop():

    while True:

        await asyncio.sleep(10)

        for device_id in list(devices.keys()):

            update_device_status(device_id)


@app.on_event("startup")
async def startup_event():

    asyncio.create_task(
        status_cleanup_loop()
    )

    print("================================")
    print(" JARVIS CLOUD RELAY")
    print("================================")
    print("Server started")


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv("PORT", "8000")
    )

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )