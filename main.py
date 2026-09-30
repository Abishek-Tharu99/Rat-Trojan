import asyncio
import json
import os
import time
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


# ============================================================
# CONFIG
# ============================================================

LAB_SECRET = os.getenv("LAB_SECRET", "LAB-123456")

STALE_TIMEOUT = 30


# Commands that are allowed through the cloud relay.
#
# Camera / microphone / screen capture are deliberately NOT
# remotely activated by this relay. Those features must be
# started through an explicit local Android consent flow.
ALLOWED_COMMANDS = {
    "device_info",
    "battery_status",
    "connection_status",
    "location_request",
    "ping",
}


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="JARVIS Cloud Relay",
    version="2.0.0",
)


# ============================================================
# DEVICE REGISTRY
# ============================================================

devices: Dict[str, dict] = {}

connections: Dict[str, WebSocket] = {}

device_info: Dict[str, dict] = {}

registry_lock = asyncio.Lock()


# ============================================================
# TIME
# ============================================================

def now() -> float:
    return time.time()


# ============================================================
# DEVICE STATUS
# ============================================================

def is_device_online(device_id: str) -> bool:

    websocket = connections.get(device_id)

    if websocket is None:
        return False

    device = devices.get(device_id)

    if device is None:
        return False

    last_seen = device.get("last_seen", 0)

    if now() - last_seen > STALE_TIMEOUT:
        return False

    return True


def update_device_status(device_id: str):

    device = devices.get(device_id)

    if device is None:
        return

    device["status"] = (
        "online"
        if is_device_online(device_id)
        else "offline"
    )


# ============================================================
# REGISTER DEVICE
# ============================================================

async def register_device(
    device_id: str,
    device_type: str,
    websocket: WebSocket,
):

    async with registry_lock:

        # If an old connection exists for the same device,
        # replace it with this connection.
        old_connection = connections.get(device_id)

        if old_connection is not None:
            try:
                await old_connection.close()
            except Exception:
                pass

        connections[device_id] = websocket

        existing = devices.get(device_id)

        if existing is None:

            devices[device_id] = {
                "device_id": device_id,
                "device_type": device_type,
                "status": "online",
                "connected_at": now(),
                "last_seen": now(),
                "info": {},
            }

        else:

            existing["device_type"] = device_type
            existing["status"] = "online"
            existing["last_seen"] = now()

        if device_id not in device_info:
            device_info[device_id] = {}


# ============================================================
# UNREGISTER
# ============================================================

def unregister_device(
    device_id: str,
    websocket: WebSocket,
):

    current = connections.get(device_id)

    # Don't mark a newer connection offline when an older
    # connection disconnects.
    if current is not websocket:
        return

    connections.pop(
        device_id,
        None,
    )

    device = devices.get(device_id)

    if device is not None:

        device["status"] = "offline"
        device["last_seen"] = now()


# ============================================================
# TOUCH DEVICE
# ============================================================

def touch_device(device_id: str):

    device = devices.get(device_id)

    if device is None:
        return

    device["last_seen"] = now()
    device["status"] = "online"


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

    except Exception as exc:

        print(
            f"[SEND ERROR] {exc}"
        )

        return False


# ============================================================
# GET SOCKET
# ============================================================

def get_device_socket(
    device_id: str,
) -> Optional[WebSocket]:

    if not is_device_online(device_id):
        return None

    return connections.get(device_id)


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
        "version": "2.0.0",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    online = 0

    for device_id in devices:

        update_device_status(device_id)

        if devices[device_id].get(
            "status"
        ) == "online":

            online += 1

    return {
        "status": "healthy",
        "devices": len(devices),
        "online": online,
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
async def websocket_endpoint(
    websocket: WebSocket,
):

    await websocket.accept()

    current_device_id = None
    current_device_type = None

    try:

        while True:

            message = await websocket.receive()

            # =================================================
            # TEXT
            # =================================================

            if message.get("text") is not None:

                raw_text = message["text"]

                try:

                    data = json.loads(
                        raw_text
                    )

                except json.JSONDecodeError:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Invalid JSON",
                        },
                    )

                    continue

                message_type = data.get(
                    "type"
                )

                # =============================================
                # ANDROID PAIRING
                # =============================================

                if message_type == "pair_request":

                    secret = data.get(
                        "secret"
                    )

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

                    device_id = data.get(
                        "device_id"
                    )

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
                        f"[PAIR] "
                        f"{device_id} "
                        f"({device_type})"
                    )

                    continue

                # =============================================
                # PC REGISTRATION
                # =============================================

                if message_type == "pc_register":

                    secret = data.get(
                        "secret"
                    )

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
                        "pc-main",
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
                        f"[PC] "
                        f"{device_id}"
                    )

                    continue

                # =============================================
                # MUST REGISTER FIRST
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

                # =============================================
                # TOUCH
                # =============================================

                touch_device(
                    current_device_id
                )

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
                # DEVICE INFO
                # =============================================

                if message_type == "device_info":

                    info = data.get(
                        "info",
                        {},
                    )

                    if isinstance(
                        info,
                        dict,
                    ):

                        device_info[
                            current_device_id
                        ] = info

                        if current_device_id in devices:

                            devices[
                                current_device_id
                            ]["info"] = info

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
                # COMMAND
                # =============================================

                if message_type == "command":

                    target_device_id = data.get(
                        "device_id"
                    )

                    command = data.get(
                        "command"
                    )

                    command_id = data.get(
                        "command_id"
                    )

                    args = data.get(
                        "args",
                        {},
                    )

                    if not target_device_id:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": command_id,
                                "message": "Missing device_id",
                            },
                        )

                        continue

                    if not command:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": command_id,
                                "message": "Missing command",
                            },
                        )

                        continue

                    # =========================================
                    # SENSITIVE MEDIA COMMANDS
                    # =========================================

                    sensitive_commands = {
                        "start_camera",
                        "stop_camera",
                        "camera_front",
                        "camera_back",
                        "camera_switch",
                        "start_microphone",
                        "stop_microphone",
                        "start_screen",
                        "stop_screen",
                    }

                    if command in sensitive_commands:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": command_id,
                                "device_id": target_device_id,
                                "message": (
                                    "This feature must be "
                                    "started/stopped through "
                                    "the Android app's "
                                    "explicit local consent "
                                    "flow."
                                ),
                            },
                        )

                        continue

                    # =========================================
                    # ALLOWED COMMANDS
                    # =========================================

                    if command not in ALLOWED_COMMANDS:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": command_id,
                                "device_id": target_device_id,
                                "message": (
                                    f"Unsupported command: "
                                    f"{command}"
                                ),
                            },
                        )

                        continue

                    target_socket = get_device_socket(
                        target_device_id
                    )

                    if target_socket is None:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": command_id,
                                "device_id": target_device_id,
                                "message": (
                                    f"Device "
                                    f"{target_device_id} "
                                    f"is offline"
                                ),
                            },
                        )

                        continue

                    forwarded_command = {
                        "type": "command",
                        "device_id": target_device_id,
                        "command_id": command_id,
                        "command": command,
                        "args": args,
                        "source_device_id": (
                            current_device_id
                        ),
                    }

                    sent = await send_json(
                        target_socket,
                        forwarded_command,
                    )

                    if not sent:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "command_id": command_id,
                                "device_id": target_device_id,
                                "message": (
                                    "Failed to forward "
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

                        source_device_id = (
                            PC_DEVICE_ID
                            if "PC_DEVICE_ID"
                            in globals()
                            else "pc-main"
                        )

                    target_socket = get_device_socket(
                        source_device_id
                    )

                    if target_socket is not None:

                        response = dict(
                            data
                        )

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
            # BINARY
            # =================================================

            elif message.get("bytes") is not None:

                # Binary media is not remotely activated by
                # this relay. Local Android consent flows can
                # be added separately.
                touch_device(
                    current_device_id
                )

                await send_json(
                    websocket,
                    {
                        "type": "error",
                        "message": (
                            "Binary media forwarding is "
                            "disabled by this relay."
                        ),
                    },
                )

    except WebSocketDisconnect:

        print(
            f"[DISCONNECT] "
            f"{current_device_id}"
        )

    except Exception as exc:

        print(
            f"[WEBSOCKET ERROR] "
            f"{current_device_id}: "
            f"{exc}"
        )

    finally:

        if current_device_id:

            unregister_device(
                current_device_id,
                websocket,
            )

            print(
                f"[OFFLINE] "
                f"{current_device_id}"
            )


# ============================================================
# STATUS CLEANUP
# ============================================================

async def status_cleanup_loop():

    while True:

        await asyncio.sleep(
            10
        )

        for device_id in list(
            devices.keys()
        ):

            update_device_status(
                device_id
            )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
async def startup_event():

    asyncio.create_task(
        status_cleanup_loop()
    )

    print(
        "================================"
    )

    print(
        " JARVIS CLOUD RELAY"
    )

    print(
        "================================"
    )

    print(
        "Server started"
    )


# ============================================================
# LOCAL RUN
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000",
        )
    )

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )