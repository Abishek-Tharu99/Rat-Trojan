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

# device_id -> websocket
connections: Dict[str, WebSocket] = {}

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


async def notify_pcs(message: Dict[str, Any]):
    """
    Send an event to every connected PC agent.
    """

    dead_pcs = []

    for device_id, device in connections.items():

        if device.get("device_type") != "pc":
            continue

        websocket = device.get("websocket")

        if websocket is None:
            continue

        try:
            await send_json(
                websocket,
                message
            )

        except Exception:
            dead_pcs.append(device_id)

    for device_id in dead_pcs:
        connections.pop(device_id, None)


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


async def register_device(
    websocket: WebSocket,
    device_id: str,
    device_type: str
):

    now = time.time()

    devices[device_id] = {
        "device_id": device_id,
        "device_type": device_type,
        "status": "online",
        "connected_at": now,
        "last_seen": now
    }

    connections[device_id] = {
        "websocket": websocket,
        "device_type": device_type
    }


async def mark_offline(device_id: str):

    if device_id not in devices:
        return

    devices[device_id]["status"] = "offline"
    devices[device_id]["last_seen"] = time.time()

    connections.pop(
        device_id,
        None
    )


# ============================================================
# BASIC HTTP ROUTES
# ============================================================

@app.get("/")
async def root():

    return {
        "status": "online",
        "service": "JARVIS Render Server"
    }


@app.get("/health")
async def health():

    return {
        "status": "healthy"
    }


@app.get("/devices")
async def http_devices():

    return JSONResponse(
        content={
            "devices": build_device_list()
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

    print("NEW WEBSOCKET CONNECTION")

    try:

        while True:

            message = await websocket.receive()

            # ------------------------------------------------
            # TEXT MESSAGE
            # ------------------------------------------------

            if "text" in message:

                raw = message["text"]

                try:
                    data = json.loads(raw)

                except json.JSONDecodeError:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message": "Invalid JSON"
                        }
                    )

                    continue

                message_type = data.get("type")

                print(
                    f"[WS] type={message_type}"
                )

                # ==================================================
                # ANDROID / PC PAIRING
                # ==================================================

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
                                "success": False,
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
                                "success": False,
                                "message":
                                    "Invalid secret"
                            }
                        )

                        await websocket.close(
                            code=1008
                        )

                        return

                    current_device_id = device_id
                    current_device_type = device_type

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
                            "success": True,
                            "device_id":
                                device_id,
                            "device_type":
                                device_type,
                            "message":
                                "Paired successfully"
                        }
                    )

                    print(
                        f"[ONLINE] "
                        f"{device_type}: "
                        f"{device_id}"
                    )

                    # Notify every PC
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

                # ==================================================
                # PC REGISTRATION
                # ==================================================

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
                                "success": False,
                                "message":
                                    "Invalid secret"
                            }
                        )

                        await websocket.close(
                            code=1008
                        )

                        return

                    current_device_id = device_id
                    current_device_type = "pc"

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
                            "success": True,
                            "device_id":
                                device_id
                        }
                    )

                    # Give PC the current devices immediately
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

                # ==================================================
                # LIST DEVICES
                # ==================================================

                if message_type == "list_devices":

                    device_list = build_device_list()

                    await send_json(
                        websocket,
                        {
                            "type":
                                "devices",
                            "devices":
                                device_list
                        }
                    )

                    print(
                        f"[DEVICES] "
                        f"{len(device_list)} devices"
                    )

                    continue

                # ==================================================
                # HEARTBEAT
                # ==================================================

                if message_type == "heartbeat":

                    if current_device_id:

                        if current_device_id in devices:

                            devices[
                                current_device_id
                            ]["last_seen"] = time.time()

                            devices[
                                current_device_id
                            ]["status"] = "online"

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

                # ==================================================
                # PING
                # ==================================================

                if message_type == "ping":

                    await send_json(
                        websocket,
                        {
                            "type": "pong"
                        }
                    )

                    continue

                # ==================================================
                # DEVICE INFO
                # ==================================================

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
                            ]["last_seen"] = time.time()

                    continue

                # ==================================================
                # COMMAND RESPONSE
                # ==================================================

                if message_type == "command_response":

                    command_id = data.get(
                        "command_id"
                    )

                    print(
                        f"[COMMAND RESPONSE] "
                        f"{command_id}"
                    )

                    # Forward Android response
                    # to the PC.

                    sender_id = current_device_id

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

                # ==================================================
                # COMMAND FROM PC
                # ==================================================

                if message_type == "command":

                    target_device_id = data.get(
                        "device_id"
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

                    target_socket = target.get(
                        "websocket"
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

                    # ------------------------------------------
                    # Forward command
                    # ------------------------------------------

                    command = data.get(
                        "command"
                    )

                    command_id = data.get(
                        "command_id"
                    )

                    await send_json(
                        target_socket,
                        {
                            "type":
                                "command",
                            "command_id":
                                command_id,
                            "command":
                                command
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

                # ==================================================
                # UNKNOWN MESSAGE
                # ==================================================

                print(
                    "[UNKNOWN]",
                    data
                )

            # ------------------------------------------------
            # BINARY MESSAGE
            # ------------------------------------------------

            elif "bytes" in message:

                payload = message["bytes"]

                if len(payload) < 1:
                    continue

                packet_type = payload[0]
                packet_data = payload[1:]

                # Forward Android binary data to PC
                # without interpreting the sensor data.

                if current_device_id:

                    dead_pcs = []

                    for pc_id, pc in connections.items():

                        if pc.get(
                            "device_type"
                        ) != "pc":
                            continue

                        pc_socket = pc.get(
                            "websocket"
                        )

                        if pc_socket is None:
                            continue

                        try:

                            # Prefix source ID as JSON
                            # text before binary data.

                            await send_json(
                                pc_socket,
                                {
                                    "type":
                                        "binary_data",
                                    "device_id":
                                        current_device_id,
                                    "packet_type":
                                        packet_type,
                                    "size":
                                        len(packet_data)
                                }
                            )

                            await pc_socket.send_bytes(
                                payload
                            )

                        except Exception:

                            dead_pcs.append(
                                pc_id
                            )

                    for pc_id in dead_pcs:

                        connections.pop(
                            pc_id,
                            None
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

            # Tell PCs that this device went offline.
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