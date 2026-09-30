import asyncio
import json
import os
import time
import uuid
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


# ============================================================
# CONFIG
# ============================================================

LAB_SECRET = os.getenv(
    "LAB_SECRET",
    "LAB-123456",
)

PC_DEVICE_ID = "pc-main"

STALE_TIMEOUT = 30


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="JARVIS Cloud Relay",
    version="3.1.0",
)


# ============================================================
# DEVICE REGISTRY
# ============================================================

devices: Dict[str, dict] = {}

connections: Dict[str, WebSocket] = {}

device_info: Dict[str, dict] = {}

registry_lock = asyncio.Lock()


# ============================================================
# LOCATION REGISTRY
# ============================================================

# Latest known location for each device.
locations: Dict[str, dict] = {}


# ============================================================
# BINARY METADATA
# ============================================================

pending_binary_metadata: Dict[str, dict] = {}


# ============================================================
# TIME
# ============================================================

def now() -> float:
    return time.time()


# ============================================================
# REQUEST ID
# ============================================================

def make_request_id() -> str:
    return uuid.uuid4().hex[:12]


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

    last_seen = device.get(
        "last_seen",
        0,
    )

    if now() - last_seen > STALE_TIMEOUT:
        return False

    return True


def update_device_status(
    device_id: str,
):

    device = devices.get(
        device_id
    )

    if device is None:
        return

    if is_device_online(
        device_id
    ):
        device["status"] = "online"

    else:
        device["status"] = "offline"


# ============================================================
# REGISTER DEVICE
# ============================================================

async def register_device(
    device_id: str,
    device_type: str,
    websocket: WebSocket,
):

    async with registry_lock:

        old_connection = connections.get(
            device_id
        )

        if (
            old_connection is not None
            and old_connection is not websocket
        ):

            try:
                await old_connection.close()

            except Exception:
                pass

        connections[
            device_id
        ] = websocket

        existing = devices.get(
            device_id
        )

        if existing is None:

            devices[
                device_id
            ] = {

                "device_id":
                    device_id,

                "device_type":
                    device_type,

                "status":
                    "online",

                "connected_at":
                    now(),

                "last_seen":
                    now(),

                "info":
                    {},
            }

        else:

            existing[
                "device_type"
            ] = device_type

            existing[
                "status"
            ] = "online"

            existing[
                "last_seen"
            ] = now()

        if device_id not in device_info:

            device_info[
                device_id
            ] = {}


# ============================================================
# UNREGISTER DEVICE
# ============================================================

def unregister_device(
    device_id: str,
    websocket: WebSocket,
):

    current = connections.get(
        device_id
    )

    if current is not websocket:
        return

    connections.pop(
        device_id,
        None,
    )

    pending_binary_metadata.pop(
        device_id,
        None,
    )

    device = devices.get(
        device_id
    )

    if device is not None:

        device[
            "status"
        ] = "offline"

        device[
            "last_seen"
        ] = now()


# ============================================================
# TOUCH DEVICE
# ============================================================

def touch_device(
    device_id: str,
):

    if not device_id:
        return

    device = devices.get(
        device_id
    )

    if device is None:
        return

    device[
        "last_seen"
    ] = now()

    device[
        "status"
    ] = "online"


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

        await websocket.send_json(
            data
        )

        return True

    except Exception as exc:

        print(
            f"[SEND ERROR] {exc}"
        )

        return False


# ============================================================
# SEND BINARY
# ============================================================

async def send_binary(
    websocket: Optional[WebSocket],
    payload: bytes,
) -> bool:

    if websocket is None:
        return False

    try:

        await websocket.send_bytes(
            payload
        )

        return True

    except Exception as exc:

        print(
            f"[BINARY SEND ERROR] {exc}"
        )

        return False


# ============================================================
# GET DEVICE SOCKET
# ============================================================

def get_device_socket(
    device_id: str,
) -> Optional[WebSocket]:

    if not is_device_online(
        device_id
    ):
        return None

    return connections.get(
        device_id
    )


# ============================================================
# DEVICE LIST
# ============================================================

def build_device_list():

    result = []

    for device_id, device in devices.items():

        update_device_status(
            device_id
        )

        result.append(

            {
                "device_id":
                    device_id,

                "device_type":
                    device.get(
                        "device_type",
                        "unknown",
                    ),

                "status":
                    device.get(
                        "status",
                        "offline",
                    ),

                "connected_at":
                    device.get(
                        "connected_at"
                    ),

                "last_seen":
                    device.get(
                        "last_seen"
                    ),

                "info":
                    device_info.get(
                        device_id,
                        {},
                    ),

                "location":
                    locations.get(
                        device_id
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

        "service":
            "JARVIS Cloud Relay",

        "status":
            "running",

        "version":
            "3.1.0",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    online = 0

    for device_id in devices:

        update_device_status(
            device_id
        )

        if (
            devices[
                device_id
            ].get(
                "status"
            )
            == "online"
        ):

            online += 1

    return {

        "status":
            "healthy",

        "devices":
            len(devices),

        "online":
            online,
    }


# ============================================================
# DEVICES
# ============================================================

@app.get("/devices")
async def get_devices():

    return {

        "devices":
            build_device_list()
    }


# ============================================================
# LOCATIONS
# ============================================================

@app.get("/locations")
async def get_locations():

    return {

        "locations":
            locations
    }


# ============================================================
# FORWARD COMMAND
# ============================================================

async def forward_command(
    source_device_id: str,
    target_device_id: str,
    command: str,
    args: dict,
    request_id: str,
):

    target_socket = get_device_socket(
        target_device_id
    )

    if target_socket is None:

        source_socket = get_device_socket(
            source_device_id
        )

        await send_json(

            source_socket,

            {
                "type":
                    "command_response",

                "request_id":
                    request_id,

                "success":
                    False,

                "device_id":
                    target_device_id,

                "error":
                    (
                        "device_offline:"
                        f"{target_device_id}"
                    ),
            },
        )

        return

    forwarded = {

        "type":
            "command",

        "request_id":
            request_id,

        "command":
            command,

        "args":
            args,

        "device_id":
            target_device_id,

        "source_device_id":
            source_device_id,
    }

    sent = await send_json(
        target_socket,
        forwarded,
    )

    if not sent:

        source_socket = get_device_socket(
            source_device_id
        )

        await send_json(

            source_socket,

            {
                "type":
                    "command_response",

                "request_id":
                    request_id,

                "success":
                    False,

                "device_id":
                    target_device_id,

                "error":
                    "command_forward_failed",
            },
        )

        return

    print(
        f"[COMMAND] "
        f"{source_device_id} -> "
        f"{target_device_id} : "
        f"{command}"
    )


# ============================================================
# FORWARD MEDIA METADATA
# ============================================================

async def forward_media_metadata(
    source_device_id: str,
    metadata: dict,
):

    target_device_id = metadata.get(
        "target_device_id",
        PC_DEVICE_ID,
    )

    target_socket = get_device_socket(
        target_device_id
    )

    if target_socket is None:

        print(
            "[MEDIA] target offline:",
            target_device_id,
        )

        return False

    metadata = dict(
        metadata
    )

    metadata[
        "source_device_id"
    ] = source_device_id

    metadata[
        "target_device_id"
    ] = target_device_id

    pending_binary_metadata[
        source_device_id
    ] = metadata

    return True


# ============================================================
# FORWARD MEDIA BINARY
# ============================================================

async def forward_media_binary(
    source_device_id: str,
    payload: bytes,
):

    metadata = pending_binary_metadata.pop(
        source_device_id,
        None,
    )

    if metadata is None:

        print(
            "[MEDIA] binary received "
            "without metadata"
        )

        return False

    target_device_id = metadata.get(
        "target_device_id",
        PC_DEVICE_ID,
    )

    target_socket = get_device_socket(
        target_device_id
    )

    if target_socket is None:

        print(
            "[MEDIA] target offline:",
            target_device_id,
        )

        return False

    metadata[
        "size"
    ] = len(payload)

    metadata[
        "timestamp"
    ] = now()

    sent_metadata = await send_json(
        target_socket,
        metadata,
    )

    if not sent_metadata:
        return False

    sent_binary = await send_binary(
        target_socket,
        payload,
    )

    if not sent_binary:
        return False

    media_type = metadata.get(
        "type",
        "unknown",
    )

    print(
        f"[MEDIA] "
        f"{source_device_id} -> "
        f"{target_device_id} "
        f"{media_type} "
        f"{len(payload)} bytes"
    )

    return True


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

    print(
        "[WS] connection accepted"
    )

    try:

        while True:

            message = await websocket.receive()

            # =================================================
            # TEXT
            # =================================================

            if message.get(
                "text"
            ) is not None:

                raw_text = message[
                    "text"
                ]

                try:

                    data = json.loads(
                        raw_text
                    )

                except json.JSONDecodeError:

                    await send_json(

                        websocket,

                        {
                            "type":
                                "error",

                            "message":
                                "invalid_json",
                        },
                    )

                    continue

                message_type = data.get(
                    "type"
                )

                # =============================================
                # ANDROID PAIR
                # =============================================

                if (
                    message_type
                    == "pair_request"
                ):

                    secret = data.get(
                        "secret"
                    )

                    if secret != LAB_SECRET:

                        await send_json(

                            websocket,

                            {
                                "type":
                                    "pair_response",

                                "success":
                                    False,

                                "message":
                                    "invalid_secret",
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
                                "type":
                                    "pair_response",

                                "success":
                                    False,

                                "message":
                                    "missing_device_id",
                            },
                        )

                        continue

                    current_device_id = (
                        device_id
                    )

                    current_device_type = (
                        device_type
                    )

                    await register_device(

                        device_id,
                        device_type,
                        websocket,
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

                            "message":
                                "Device paired successfully",
                        },
                    )

                    print(
                        f"[PAIR] "
                        f"{device_id} "
                        f"({device_type})"
                    )

                    continue

                # =============================================
                # PC REGISTER
                # =============================================

                if (
                    message_type
                    == "pc_register"
                ):

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
                                    "invalid_secret",
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

                    current_device_id = (
                        device_id
                    )

                    current_device_type = (
                        device_type
                    )

                    await register_device(

                        device_id,
                        device_type,
                        websocket,
                    )

                    # Store PC info if supplied.
                    info = data.get(
                        "info",
                        {},
                    )

                    if isinstance(
                        info,
                        dict,
                    ):

                        device_info[
                            device_id
                        ] = info

                        devices[
                            device_id
                        ][
                            "info"
                        ] = info

                    await send_json(

                        websocket,

                        {
                            "type":
                                "pc_register_response",

                            "success":
                                True,

                            "device_id":
                                device_id,

                            "message":
                                "PC registered successfully",
                        },
                    )

                    print(
                        f"[PC] "
                        f"{device_id}"
                    )

                    continue

                # =============================================
                # MUST REGISTER
                # =============================================

                if current_device_id is None:

                    await send_json(

                        websocket,

                        {
                            "type":
                                "error",

                            "message":
                                "device_not_registered",
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

                if (
                    message_type
                    == "heartbeat"
                ):

                    await send_json(

                        websocket,

                        {
                            "type":
                                "heartbeat_response",

                            "timestamp":
                                now(),
                        },
                    )

                    continue

                # =============================================
                # PING
                # =============================================

                if (
                    message_type
                    == "ping"
                ):

                    await send_json(

                        websocket,

                        {
                            "type":
                                "pong",

                            "timestamp":
                                now(),
                        },
                    )

                    continue

                # =============================================
                # LIST DEVICES
                # =============================================

                if (
                    message_type
                    == "list_devices"
                ):

                    await send_json(

                        websocket,

                        {
                            "type":
                                "devices",

                            "devices":
                                build_device_list(),
                        },
                    )

                    continue

                # =============================================
                # DEVICE INFO
                # =============================================

                if (
                    message_type
                    == "device_info"
                ):

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

                        if (
                            current_device_id
                            in devices
                        ):

                            devices[
                                current_device_id
                            ][
                                "info"
                            ] = info

                    await send_json(

                        websocket,

                        {
                            "type":
                                "device_info_response",

                            "success":
                                True,

                            "device_id":
                                current_device_id,

                            "info":
                                device_info.get(
                                    current_device_id,
                                    {},
                                ),
                        },
                    )

                    continue

                # =============================================
                # LOCATION
                # =============================================

                if (
                    message_type
                    == "location"
                ):

                    location = {

                        "type":
                            "location",

                        "device_id":
                            data.get(
                                "device_id",
                                current_device_id,
                            ),

                        "latitude":
                            data.get(
                                "latitude"
                            ),

                        "longitude":
                            data.get(
                                "longitude"
                            ),

                        "accuracy":
                            data.get(
                                "accuracy"
                            ),

                        "altitude":
                            data.get(
                                "altitude"
                            ),

                        "speed":
                            data.get(
                                "speed"
                            ),

                        "bearing":
                            data.get(
                                "bearing"
                            ),

                        "timestamp":
                            data.get(
                                "timestamp",
                                now(),
                            ),
                    }

                    location_device_id = (
                        location[
                            "device_id"
                        ]
                    )

                    if (
                        location_device_id
                        is None
                    ):

                        location_device_id = (
                            current_device_id
                        )

                        location[
                            "device_id"
                        ] = (
                            current_device_id
                        )

                    locations[
                        location_device_id
                    ] = location

                    print(
                        "[LOCATION] "
                        f"{location_device_id} "
                        f"lat={location['latitude']} "
                        f"lon={location['longitude']} "
                        f"accuracy={location['accuracy']}"
                    )

                    # Forward location to PC.
                    if (
                        location_device_id
                        != PC_DEVICE_ID
                    ):

                        pc_socket = (
                            get_device_socket(
                                PC_DEVICE_ID
                            )
                        )

                        if pc_socket is not None:

                            await send_json(
                                pc_socket,
                                location,
                            )

                    continue

                # =============================================
                # COMMAND
                # =============================================

                if (
                    message_type
                    == "command"
                ):

                    target_device_id = data.get(
                        "device_id"
                    )

                    command = data.get(
                        "command"
                    )

                    args = data.get(
                        "args",
                        {},
                    )

                    request_id = data.get(
                        "request_id"
                    )

                    if not request_id:

                        request_id = data.get(
                            "command_id"
                        )

                    if not request_id:

                        request_id = (
                            make_request_id()
                        )

                    if not target_device_id:

                        await send_json(

                            websocket,

                            {
                                "type":
                                    "command_response",

                                "request_id":
                                    request_id,

                                "success":
                                    False,

                                "error":
                                    "missing_device_id",
                            },
                        )

                        continue

                    if not command:

                        await send_json(

                            websocket,

                            {
                                "type":
                                    "command_response",

                                "request_id":
                                    request_id,

                                "success":
                                    False,

                                "error":
                                    "missing_command",
                            },
                        )

                        continue

                    if not isinstance(
                        args,
                        dict,
                    ):

                        args = {}

                    await forward_command(

                        source_device_id=
                            current_device_id,

                        target_device_id=
                            target_device_id,

                        command=
                            command,

                        args=
                            args,

                        request_id=
                            request_id,
                    )

                    continue

                # =============================================
                # COMMAND RESPONSE
                # =============================================

                if (
                    message_type
                    == "command_response"
                ):

                    target_device_id = data.get(
                        "target_device_id"
                    )

                    source_device_id = data.get(
                        "source_device_id"
                    )

                    if not target_device_id:

                        target_device_id = (
                            source_device_id
                        )

                    if not target_device_id:

                        target_device_id = (
                            PC_DEVICE_ID
                        )

                    target_socket = (
                        get_device_socket(
                            target_device_id
                        )
                    )

                    response = dict(
                        data
                    )

                    response[
                        "response_device_id"
                    ] = current_device_id

                    response[
                        "source_device_id"
                    ] = current_device_id

                    if target_socket is not None:

                        await send_json(

                            target_socket,
                            response,
                        )

                    continue

                # =============================================
                # MEDIA METADATA
                # =============================================

                if message_type in {

                    "camera_frame",

                    "screen_frame",

                    "microphone_chunk",

                }:

                    await forward_media_metadata(

                        current_device_id,
                        data,
                    )

                    continue

                # =============================================
                # UNKNOWN
                # =============================================

                await send_json(

                    websocket,

                    {
                        "type":
                            "error",

                        "message":
                            (
                                "unknown_message_type:"
                                f"{message_type}"
                            ),
                    },
                )

            # =================================================
            # BINARY
            # =================================================

            elif message.get(
                "bytes"
            ) is not None:

                payload = message[
                    "bytes"
                ]

                touch_device(
                    current_device_id
                )

                await forward_media_binary(

                    current_device_id,
                    payload,
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

@app.on_event(
    "startup"
)
async def startup_event():

    asyncio.create_task(
        status_cleanup_loop()
    )

    print(
        "================================"
    )

    print(
        "       JARVIS CLOUD RELAY"
    )

    print(
        "================================"
    )

    print(
        f"PC DEVICE ID: {PC_DEVICE_ID}"
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