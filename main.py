import json
import time
from typing import Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse


app = FastAPI()


# ============================================================
# CONFIG
# ============================================================

LAB_SECRET = "LAB-123456"


# ============================================================
# DEVICE REGISTRY
# ============================================================

devices: Dict[str, Dict[str, Any]] = {}

# device_id -> connection information
connections: Dict[str, Dict[str, Any]] = {}

# device_id -> device information
device_info: Dict[str, Dict[str, Any]] = {}


# ============================================================
# HELPERS
# ============================================================

async def send_json(
    websocket: WebSocket,
    data: Dict[str, Any]
):
    await websocket.send_text(
        json.dumps(data)
    )


def build_device_list():

    result = []

    for device_id, device in devices.items():

        result.append({
            "device_id": device_id,

            "device_type": device.get(
                "device_type",
                "unknown"
            ),

            "status": device.get(
                "status",
                "offline"
            ),

            "connected_at": device.get(
                "connected_at"
            ),

            "last_seen": device.get(
                "last_seen"
            ),

            "info": device_info.get(
                device_id,
                {}
            )
        })

    return result


async def notify_pcs(
    message: Dict[str, Any]
):

    dead_pcs = []

    for device_id, connection in list(
        connections.items()
    ):

        if connection.get(
            "device_type"
        ) != "pc":

            continue

        websocket = connection.get(
            "websocket"
        )

        if websocket is None:
            continue

        try:

            await send_json(
                websocket,
                message
            )

        except Exception as e:

            print(
                f"[PC ERROR] "
                f"{device_id}: {e}"
            )

            dead_pcs.append(
                device_id
            )

    for device_id in dead_pcs:

        connections.pop(
            device_id,
            None
        )


async def register_device(
    websocket: WebSocket,
    device_id: str,
    device_type: str
):

    now = time.time()

    devices[device_id] = {

        "device_id":
            device_id,

        "device_type":
            device_type,

        "status":
            "online",

        "connected_at":
            now,

        "last_seen":
            now
    }

    connections[device_id] = {

        "websocket":
            websocket,

        "device_type":
            device_type
    }

    print(
        f"[REGISTER] "
        f"{device_type} "
        f"{device_id} "
        f"-> ONLINE"
    )


async def mark_offline(
    device_id: str
):

    if device_id not in devices:
        return

    devices[device_id][
        "status"
    ] = "offline"

    devices[device_id][
        "last_seen"
    ] = time.time()

    connections.pop(
        device_id,
        None
    )


# ============================================================
# HTTP
# ============================================================

@app.get("/")
async def root():

    return {
        "status":
            "online",

        "service":
            "JARVIS Render Server"
    }


@app.get("/health")
async def health():

    return {

        "status":
            "healthy",

        "devices":
            len(devices),

        "online":
            sum(
                1
                for device in devices.values()
                if device.get("status")
                == "online"
            )
    }


@app.get("/devices")
async def http_devices():

    return JSONResponse(
        content={
            "devices":
                build_device_list()
        }
    )


# ============================================================
# WEBSOCKET
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    current_device_id = None
    current_device_type = None

    print(
        "[WS] NEW CONNECTION"
    )

    try:

        while True:

            message = await websocket.receive()

            # ====================================================
            # TEXT
            # ====================================================

            if "text" in message:

                raw = message["text"]

                try:

                    data = json.loads(
                        raw
                    )

                except json.JSONDecodeError:

                    await send_json(
                        websocket,
                        {
                            "type":
                                "error",

                            "message":
                                "Invalid JSON"
                        }
                    )

                    continue

                message_type = data.get(
                    "type"
                )

                print(
                    f"[WS] "
                    f"type={message_type}"
                )

                # =================================================
                # ANDROID PAIRING
                # =================================================

                if message_type == "pair_request":

                    device_id = data.get(
                        "device_id"
                    )

                    device_type = data.get(
                        "device_type",
                        "unknown"
                    )

                    secret = data.get(
                        "secret"
                    )

                    if not device_id:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "pair_response",

                                "success":
                                    False,

                                "message":
                                    "Missing device_id"
                            }
                        )

                        continue

                    if secret != LAB_SECRET:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "pair_response",

                                "success":
                                    False,

                                "message":
                                    "Invalid secret"
                            }
                        )

                        await websocket.close(
                            code=1008
                        )

                        return

                    current_device_id = (
                        device_id
                    )

                    current_device_type = (
                        device_type
                    )

                    await register_device(
                        websocket,
                        device_id,
                        device_type
                    )

                    await send_json(
                        websocket,
                        {
                            "type":
                                "pair_response",

                            "success":
                                True,

                            "device_id":
                                device_id,

                            "device_type":
                                device_type,

                            "message":
                                "Paired successfully"
                        }
                    )

                    await notify_pcs(
                        {
                            "type":
                                "device_connected",

                            "device_id":
                                device_id,

                            "device_type":
                                device_type,

                            "status":
                                "online"
                        }
                    )

                    continue

                # =================================================
                # PC REGISTRATION
                # =================================================

                if message_type == "pc_register":

                    device_id = data.get(
                        "device_id",
                        "pc-main"
                    )

                    secret = data.get(
                        "secret"
                    )

                    if secret != LAB_SECRET:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "pc_register_response",

                                "success":
                                    False,

                                "message":
                                    "Invalid secret"
                            }
                        )

                        await websocket.close(
                            code=1008
                        )

                        return

                    current_device_id = (
                        device_id
                    )

                    current_device_type = (
                        "pc"
                    )

                    await register_device(
                        websocket,
                        device_id,
                        "pc"
                    )

                    await send_json(
                        websocket,
                        {
                            "type":
                                "pc_register_response",

                            "success":
                                True,

                            "device_id":
                                device_id,

                            "status":
                                "online"
                        }
                    )

                    await send_json(
                        websocket,
                        {
                            "type":
                                "devices",

                            "devices":
                                build_device_list()
                        }
                    )

                    print(
                        f"[PC ONLINE] "
                        f"{device_id}"
                    )

                    continue

                # =================================================
                # LIST DEVICES
                # =================================================

                if message_type == "list_devices":

                    await send_json(
                        websocket,
                        {
                            "type":
                                "devices",

                            "devices":
                                build_device_list()
                        }
                    )

                    continue

                # =================================================
                # HEARTBEAT
                # =================================================

                if message_type == "heartbeat":

                    if current_device_id:

                        device = devices.get(
                            current_device_id
                        )

                        if device:

                            device[
                                "status"
                            ] = "online"

                            device[
                                "last_seen"
                            ] = time.time()

                    await send_json(
                        websocket,
                        {
                            "type":
                                "heartbeat_ack",

                            "timestamp":
                                time.time()
                        }
                    )

                    continue

                # =================================================
                # PING
                # =================================================

                if message_type == "ping":

                    await send_json(
                        websocket,
                        {
                            "type":
                                "pong"
                        }
                    )

                    continue

                # =================================================
                # DEVICE INFO
                # =================================================

                if message_type == "device_info":

                    device_id = data.get(
                        "device_id"
                    )

                    if device_id:

                        device_info[
                            device_id
                        ] = data.get(
                            "data",
                            {}
                        )

                        if device_id in devices:

                            devices[
                                device_id
                            ][
                                "last_seen"
                            ] = time.time()

                            devices[
                                device_id
                            ][
                                "status"
                            ] = "online"

                    continue

                # =================================================
                # COMMAND RESPONSE
                # =================================================

                if message_type == "command_response":

                    command_id = data.get(
                        "command_id"
                    )

                    sender_id = (
                        current_device_id
                    )

                    print(
                        f"[COMMAND RESPONSE] "
                        f"{sender_id} "
                        f"{command_id}"
                    )

                    if sender_id:

                        await notify_pcs(
                            {
                                "type":
                                    "command_response",

                                "device_id":
                                    sender_id,

                                "command_id":
                                    command_id,

                                "data":
                                    data.get(
                                        "data"
                                    ),

                                "success":
                                    data.get(
                                        "success",
                                        True
                                    )
                            }
                        )

                    continue

                # =================================================
                # COMMAND
                # =================================================

                if message_type == "command":

                    target_device_id = (
                        data.get(
                            "device_id"
                        )
                    )

                    if not target_device_id:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "error",

                                "message":
                                    "Missing target device_id"
                            }
                        )

                        continue

                    target = connections.get(
                        target_device_id
                    )

                    if target is None:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "error",

                                "message":
                                    "Device is offline",

                                "device_id":
                                    target_device_id
                            }
                        )

                        continue

                    target_socket = (
                        target.get(
                            "websocket"
                        )
                    )

                    if target_socket is None:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "error",

                                "message":
                                    "Device websocket unavailable"
                            }
                        )

                        continue

                    command = data.get(
                        "command"
                    )

                    command_id = data.get(
                        "command_id"
                    )

                    args = data.get(
                        "args",
                        {}
                    )

                    await send_json(
                        target_socket,
                        {
                            "type":
                                "command",

                            "command_id":
                                command_id,

                            "command":
                                command,

                            "args":
                                args
                        }
                    )

                    print(
                        f"[COMMAND] "
                        f"{current_device_id} "
                        f"-> "
                        f"{target_device_id} "
                        f": "
                        f"{command}"
                    )

                    continue

                # =================================================
                # STREAM METADATA
                # =================================================

                if message_type in (
                    "camera_frame",
                    "screen_frame",
                    "microphone_chunk"
                ):

                    source_device = (
                        current_device_id
                    )

                    target_device = data.get(
                        "target_device_id",
                        "pc-main"
                    )

                    target = connections.get(
                        target_device
                    )

                    if target is None:

                        print(
                            f"[STREAM] "
                            f"Target offline: "
                            f"{target_device}"
                        )

                        continue

                    target_socket = (
                        target.get(
                            "websocket"
                        )
                    )

                    if target_socket is None:
                        continue

                    metadata = dict(
                        data
                    )

                    metadata[
                        "source_device_id"
                    ] = source_device

                    metadata[
                        "timestamp"
                    ] = time.time()

                    await send_json(
                        target_socket,
                        metadata
                    )

                    print(
                        f"[STREAM] "
                        f"{message_type} "
                        f"{source_device} "
                        f"-> "
                        f"{target_device}"
                    )

                    continue

                # =================================================
                # UNKNOWN
                # =================================================

                print(
                    "[UNKNOWN]",
                    data
                )

            # ====================================================
            # BINARY
            # ====================================================

            elif "bytes" in message:

                payload = message[
                    "bytes"
                ]

                if not payload:
                    continue

                if not current_device_id:
                    continue

                # ------------------------------------------------
                # Forward raw binary to PC.
                #
                # The metadata was already forwarded immediately
                # before this binary packet.
                # ------------------------------------------------

                target_device = "pc-main"

                target = connections.get(
                    target_device
                )

                if target is None:

                    print(
                        "[BINARY] "
                        "PC is offline"
                    )

                    continue

                target_socket = (
                    target.get(
                        "websocket"
                    )
                )

                if target_socket is None:
                    continue

                try:

                    await target_socket.send_bytes(
                        payload
                    )

                    print(
                        f"[BINARY] "
                        f"{current_device_id} "
                        f"-> "
                        f"{target_device} "
                        f"{len(payload)} bytes"
                    )

                except Exception as e:

                    print(
                        f"[BINARY ERROR] "
                        f"{e}"
                    )

    except WebSocketDisconnect:

        print(
            f"[DISCONNECT] "
            f"{current_device_id}"
        )

    except Exception as e:

        print(
            f"[ERROR] "
            f"{current_device_id}: "
            f"{e}"
        )

    finally:

        if current_device_id:

            await mark_offline(
                current_device_id
            )

            await notify_pcs(
                {
                    "type":
                        "device_disconnected",

                    "device_id":
                        current_device_id,

                    "device_type":
                        current_device_type,

                    "status":
                        "offline"
                }
            )

            print(
                f"[OFFLINE] "
                f"{current_device_id}"
            )