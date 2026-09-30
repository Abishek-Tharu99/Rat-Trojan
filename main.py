import json
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

LAB_SECRET = "LAB-123456"

# ---------------------------------------------------------
# Device registry
# ---------------------------------------------------------

devices = {}
connections = {}
device_info = {}

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def now_iso():
    return datetime.now(timezone.utc).isoformat()


async def send_json(websocket, data):
    await websocket.send_text(json.dumps(data))


async def send_to_device(device_id, data):
    websocket = connections.get(device_id)

    if websocket is None:
        return False

    try:
        await send_json(websocket, data)
        return True

    except Exception as e:
        print(
            f"[RENDER] Failed to send to "
            f"{device_id}: {e}"
        )

        return False


def register_device(
    device_id,
    device_type
):
    devices[device_id] = {
        "device_id": device_id,
        "device_type": device_type,
        "online": True,
        "last_seen": now_iso(),
    }


def update_last_seen(device_id):
    if device_id in devices:
        devices[device_id]["last_seen"] = now_iso()
        devices[device_id]["online"] = True


# ---------------------------------------------------------
# HTTP
# ---------------------------------------------------------

@app.get("/")
async def root():
    return {
        "service": "JARVIS Cloud Relay",
        "status": "online",
        "time": now_iso(),
    }


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "devices_online": len(connections),
    }


@app.get("/devices")
async def get_devices():
    return {
        "devices": list(devices.values())
    }


# ---------------------------------------------------------
# WebSocket
# ---------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    device_id = None
    device_type = None

    # Metadata describing the next binary packet.
    #
    # This fixes the previous "unknown device"
    # problem.
    pending_binary_metadata = None

    print(
        "[RENDER] WebSocket connection accepted"
    )

    try:

        while True:

            message = await websocket.receive()

            # =================================================
            # TEXT MESSAGE
            # =================================================

            if message.get("text") is not None:

                text = message["text"]

                try:
                    data = json.loads(text)

                except json.JSONDecodeError:

                    print(
                        "[RENDER] Invalid JSON"
                    )

                    continue

                msg_type = data.get("type")

                # -------------------------------------------------
                # Android / PC pairing
                # -------------------------------------------------

                if msg_type == "pair_request":

                    requested_id =data.get("device_id")

                    requested_type =data.get("device_type")

                    secret =data.get("secret")

                    if secret != LAB_SECRET:

                        await send_json(
                            websocket,
                            {
                                "type": "pair_response",
                                "success": False,
                                "error": "invalid_secret",
                            },
                        )

                        continue

                    if not requested_id:

                        await send_json(
                            websocket,
                            {
                                "type": "pair_response",
                                "success": False,
                                "error": "missing_device_id",
                            },
                        )

                        continue

                    device_id = requested_id
                    device_type = requested_type

                    connections[device_id] = websocket

                    register_device(
                        device_id,
                        device_type
                    )

                    await send_json(
                        websocket,
                        {
                            "type": "pair_response",
                            "success": True,
                            "device_id": device_id,
                        },
                    )

                    print(
                        f"[RENDER] Paired: "
                        f"{device_id} "
                        f"({device_type})"
                    )

                    continue

                # -------------------------------------------------
                # PC registration
                # -------------------------------------------------

                if msg_type == "pc_register":

                    secret =data.get("secret")

                    if secret != LAB_SECRET:

                        await send_json(
                            websocket,
                            {
                                "type": "pc_register_response",
                                "success": False,
                                "error": "invalid_secret",
                            },
                        )

                        continue

                    device_id =data.get(
                            "device_id",
                            "pc-main"
                        )

                    device_type = "pc"

                    connections[device_id] = websocket

                    register_device(
                        device_id,
                        device_type
                    )

                    await send_json(
                        websocket,
                        {
                            "type": "pc_register_response",
                            "success": True,
                            "device_id": device_id,
                        },
                    )

                    print(
                        "[RENDER] PC registered:",
                        device_id
                    )

                    continue

                # -------------------------------------------------
                # Everything below requires registration
                # -------------------------------------------------

                if device_id is None:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "error": "not_registered",
                        },
                    )

                    continue

                update_last_seen(device_id)

                # -------------------------------------------------
                # Heartbeat
                # -------------------------------------------------

                if msg_type == "heartbeat":

                    await send_json(
                        websocket,
                        {
                            "type": "heartbeat_ack",
                            "timestamp": now_iso(),
                        },
                    )

                    continue

                # -------------------------------------------------
                # Ping
                # -------------------------------------------------

                if msg_type == "ping":

                    await send_json(
                        websocket,
                        {
                            "type": "pong",
                            "timestamp": now_iso(),
                        },
                    )

                    continue

                # -------------------------------------------------
                # Device information
                # -------------------------------------------------

                if msg_type == "device_info":

                    device_info[device_id] = data.get(
                        "info",
                        {}
                    )

                    continue

                # -------------------------------------------------
                # Request device list
                # -------------------------------------------------

                if msg_type == "list_devices":

                    await send_json(
                        websocket,
                        {
                            "type": "devices",
                            "devices": list(
                                devices.values()
                            ),
                        },
                    )

                    continue

                # -------------------------------------------------
                # Command routing
                # -------------------------------------------------

                if msg_type == "command":

                    target_id =data.get("device_id")

                    if not target_id:

                        await send_json(
                            websocket,
                            {
                                "type": "command_response",
                                "success": False,
                                "error":
                                    "missing_device_id",
                            },
                        )

                        continue

                    target = connections.get(
                        target_id
                    )

                    if target is None:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "command_response",
                                "success": False,
                                "device_id":
                                    target_id,
                                "error":
                                    "device_offline",
                            },
                        )

                        continue

                    command_message = {
                        "type": "command",
                        "command_id":
                            data.get("command_id"),
                        "command":
                            data.get("command"),
                        "args":
                            data.get("args", {}),
                    }

                    try:

                        await send_json(
                            target,
                            command_message
                        )

                    except Exception as e:

                        print(
                            "[RENDER] Command "
                            f"routing failed: {e}"
                        )

                    continue

                # -------------------------------------------------
                # Command response
                # -------------------------------------------------

                if msg_type == "command_response":

                    target_id = data.get(
                            "target_device_id"
                        )

                    if target_id:

                        await send_to_device(
                            target_id,
                            data
                        )

                    else:

                        # If PC requested the command,
                        # send the response back through
                        # the command requester if supplied.
                        requester_id =data.get(
                                "requester_device_id"
                            )

                        if requester_id:

                            await send_to_device(
                                requester_id,
                                data
                            )

                    continue

                # -------------------------------------------------
                # Binary metadata
                #
                # Android sends:
                #
                # {
                #   type: "camera_frame",
                #   device_id: "...",
                #   ...
                # }
                #
                # immediately before the JPEG binary packet.
                # -------------------------------------------------

                if msg_type in (
                    "camera_frame",
                    "screen_frame",
                    "microphone_chunk",
                ):

                    pending_binary_metadata = data

                    continue

                # -------------------------------------------------
                # Disconnect request
                # -------------------------------------------------

                if msg_type == "disconnect":

                    break

            # =================================================
            # BINARY MESSAGE
            # =================================================

            elif message.get("bytes") is not None:

                binary_data = message["bytes"]

                if not pending_binary_metadata:

                    print(
                        "[RENDER] Binary packet received "
                        "without metadata"
                    )

                    continue

                metadata = pending_binary_metadata

                pending_binary_metadata = None

                source_device =metadata.get(
                        "device_id",
                        device_id
                    )

                stream_type = metadata.get(
                        "type",
                        "unknown"
                    )

                # -------------------------------------------------
                # Determine destination
                # -------------------------------------------------

                destination_id = metadata.get(
                        "target_device_id",
                        "pc-main"
                    )

                destination = connections.get(
                        destination_id
                    )

                if destination is None:

                    print(
                        "[RENDER] Destination offline:",
                        destination_id
                    )

                    continue

                # -------------------------------------------------
                # Forward metadata
                # -------------------------------------------------

                forward_metadata = {
                    **metadata,
                    "source_device_id":
                        source_device,
                    "size":
                        len(binary_data),
                    "timestamp":
                        now_iso(),
                }

                try:

                    await send_json(
                        destination,
                        forward_metadata
                    )

                    await destination.send_bytes(
                        binary_data
                    )

                    print(
                        "[RENDER] Forwarded",
                        stream_type,
                        "from",
                        source_device,
                        "to",
                        destination_id,
                        len(binary_data),
                        "bytes",
                    )

                except Exception as e:

                    print(
                        "[RENDER] Binary forwarding "
                        f"failed: {e}"
                    )

    except WebSocketDisconnect:

        print(
            "[RENDER] Disconnected:",
            device_id
        )

    except Exception as e:

        print(
            "[RENDER] WebSocket error:",
            e
        )

    finally:

        if device_id:

            current = connections.get(device_id)

            if current is websocket:

                connections.pop(
                    device_id,
                    None
                )

            if device_id in devices:

                devices[device_id]["online"] = False

                devices[device_id][
                    "last_seen"
                ] = now_iso()

        print(
            "[RENDER] Connection cleanup:",
            device_id
        )
