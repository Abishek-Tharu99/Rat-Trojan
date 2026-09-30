import asyncio
import json
import platform
import socket
import time
import uuid

import websockets


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = (
    "wss://rat-trojan.onrender.com/ws"
)

PC_DEVICE_ID = "pc-main"

PAIRING_SECRET = "LAB-123456"

HEARTBEAT_INTERVAL = 10

RECONNECT_DELAY = 5


# ============================================================
# STATE
# ============================================================

websocket = None

connected = False

registered = False

devices = {}


# ============================================================
# PC INFO
# ============================================================

def get_pc_info():

    return {
        "hostname": socket.gethostname(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "platform_version": platform.version(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "python_version": platform.python_version(),
        "agent_status": "active",
        "timestamp": time.time(),
    }


# ============================================================
# SEND JSON
# ============================================================

async def send_json(data):

    global websocket

    if websocket is None:
        return False

    try:

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
# REGISTER
# ============================================================

async def register_pc():

    print(
        "[RENDER] Registering PC..."
    )

    return await send_json(
        {
            "type": "pc_register",
            "device_id": PC_DEVICE_ID,
            "device_type": "pc",
            "secret": PAIRING_SECRET,
        }
    )


# ============================================================
# HEARTBEAT
# ============================================================

async def heartbeat_loop():

    while connected:

        await asyncio.sleep(
            HEARTBEAT_INTERVAL
        )

        if not connected:
            break

        await send_json(
            {
                "type": "heartbeat"
            }
        )


# ============================================================
# REQUEST DEVICES
# ============================================================

async def request_devices():

    if not connected:

        print(
            "[RENDER] Not connected"
        )

        return

    await send_json(
        {
            "type": "list_devices"
        }
    )


# ============================================================
# PRINT DEVICES
# ============================================================

def print_devices():

    print()

    print(
        "DEVICES"
    )

    print(
        f"{'DEVICE ID':<28}"
        f"{'TYPE':<12}"
        f"{'STATUS':<12}"
    )

    print(
        "-" * 70
    )

    if not devices:

        print(
            "No devices registered."
        )

        return

    for device_id, device in devices.items():

        device_type = str(
            device.get(
                "device_type",
                "unknown",
            )
        )

        status = str(
            device.get(
                "status",
                "offline",
            )
        )

        print(
            f"{device_id:<28}"
            f"{device_type:<12}"
            f"{status:<12}"
        )

    print()


# ============================================================
# SEND COMMAND
# ============================================================

async def send_command(
    device_id,
    command,
    args=None,
):

    if args is None:
        args = {}

    if not connected:

        print(
            "[JARVIS] Not connected"
        )

        return

    command_id = (
        "cmd-"
        + uuid.uuid4().hex[:8]
    )

    payload = {
        "type": "command",
        "device_id": device_id,
        "command_id": command_id,
        "command": command,
        "args": args,
    }

    print()

    print(
        f"[COMMAND] {command}"
    )

    print(
        f"[TARGET]  {device_id}"
    )

    print(
        f"[ID]      {command_id}"
    )

    sent = await send_json(
        payload
    )

    if not sent:

        print(
            "[COMMAND] Send failed"
        )


# ============================================================
# HANDLE DEVICE LIST
# ============================================================

def handle_devices(data):

    global devices

    devices = {}

    for device in data.get(
        "devices",
        [],
    ):

        device_id = device.get(
            "device_id"
        )

        if device_id:

            devices[
                device_id
            ] = device

    print_devices()


# ============================================================
# HANDLE COMMAND RESPONSE
# ============================================================

def handle_command_response(data):

    print()

    print(
        "================================"
    )

    print(
        " COMMAND RESPONSE"
    )

    print(
        "================================"
    )

    print(
        json.dumps(
            data,
            indent=2,
        )
    )

    print()


# ============================================================
# HANDLE COMMAND
# ============================================================

async def handle_command(data):

    command = data.get(
        "command"
    )

    command_id = data.get(
        "command_id"
    )

    source_device_id = data.get(
        "source_device_id"
    )

    print()

    print(
        "[COMMAND RECEIVED]"
    )

    print(
        f"Command : {command}"
    )

    print(
        f"ID      : {command_id}"
    )

    # --------------------------------------------------------
    # DEVICE INFO
    # --------------------------------------------------------

    if command == "device_info":

        response = {
            "type": "command_response",
            "success": True,
            "command_id": command_id,
            "source_device_id": source_device_id,
            "result": get_pc_info(),
        }

        await send_json(
            response
        )

        return

    # --------------------------------------------------------
    # CONNECTION STATUS
    # --------------------------------------------------------

    if command == "connection_status":

        response = {
            "type": "command_response",
            "success": True,
            "command_id": command_id,
            "source_device_id": source_device_id,
            "result": {
                "connected": connected,
                "registered": registered,
                "timestamp": time.time(),
            },
        }

        await send_json(
            response
        )

        return

    # --------------------------------------------------------
    # PING
    # --------------------------------------------------------

    if command == "ping":

        response = {
            "type": "command_response",
            "success": True,
            "command_id": command_id,
            "source_device_id": source_device_id,
            "result": {
                "message": "pong",
                "timestamp": time.time(),
            },
        }

        await send_json(
            response
        )

        return

    # --------------------------------------------------------
    # SENSITIVE COMMANDS
    # --------------------------------------------------------

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

        response = {
            "type": "command_response",
            "success": False,
            "command_id": command_id,
            "source_device_id": source_device_id,
            "message": (
                "Media capture must be "
                "started through explicit "
                "local user consent."
            ),
        }

        await send_json(
            response
        )

        return

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

    response = {
        "type": "command_response",
        "success": False,
        "command_id": command_id,
        "source_device_id": source_device_id,
        "message": (
            f"Unsupported command: "
            f"{command}"
        ),
    }

    await send_json(
        response
    )


# ============================================================
# HANDLE TEXT
# ============================================================

async def handle_text_message(
    message,
):

    global registered

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        print(
            "[RENDER] Invalid JSON"
        )

        return

    message_type = data.get(
        "type"
    )

    # ========================================================
    # PC REGISTER RESPONSE
    # ========================================================

    if message_type == "pc_register_response":

        if data.get(
            "success"
        ):

            registered = True

            print(
                "[RENDER] "
                "PC registered successfully"
            )

            # Publish PC information.
            await send_json(
                {
                    "type": "device_info",
                    "info": get_pc_info(),
                }
            )

            # Get current registry.
            await request_devices()

        else:

            registered = False

            print(
                "[RENDER] "
                "PC registration failed"
            )

            print(
                data.get(
                    "message",
                    "Unknown error",
                )
            )

        return

    # ========================================================
    # DEVICE LIST
    # ========================================================

    if message_type == "devices":

        handle_devices(
            data
        )

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

        print(
            "[RENDER] PONG"
        )

        return

    # ========================================================
    # COMMAND
    # ========================================================

    if message_type == "command":

        await handle_command(
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
                "Unknown error",
            )
        )

        return

    # ========================================================
    # UNKNOWN
    # ========================================================

    print(
        "[RENDER] Unknown message:",
        data,
    )


# ============================================================
# RECEIVE LOOP
# ============================================================

async def receive_loop():

    global connected
    global registered

    try:

        async for message in websocket:

            if isinstance(
                message,
                bytes,
            ):

                print(
                    "[RENDER] "
                    "Unexpected binary message"
                )

                continue

            await handle_text_message(
                message
            )

    except websockets.ConnectionClosed as exc:

        print()

        print(
            "[RENDER] "
            "Connection closed"
        )

        print(
            f"Code   : {exc.code}"
        )

        print(
            f"Reason : {exc.reason}"
        )

    except Exception as exc:

        print()

        print(
            "[RENDER] "
            "Receive error:",
            exc,
        )

    finally:

        connected = False
        registered = False


# ============================================================
# CONNECT
# ============================================================

async def connect_to_render():

    global websocket
    global connected
    global registered

    print()

    print(
        "[RENDER] Connecting..."
    )

    try:

        websocket = await websockets.connect(
            RENDER_URL,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=5,
            max_size=16 * 1024 * 1024,
        )

        connected = True
        registered = False

        print(
            "[RENDER] Connected"
        )

        await register_pc()

        receive_task = asyncio.create_task(
            receive_loop()
        )

        heartbeat_task = asyncio.create_task(
            heartbeat_loop()
        )

        done, pending = await asyncio.wait(
            [
                receive_task,
                heartbeat_task,
            ],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:

            task.cancel()

        for task in done:

            try:

                await task

            except asyncio.CancelledError:

                pass

    except Exception as exc:

        print()

        print(
            "[RENDER] "
            "Connection failed:",
            exc,
        )

    finally:

        connected = False
        registered = False

        try:

            if websocket is not None:

                await websocket.close()

        except Exception:
            pass

        websocket = None

        print(
            "[RENDER] Disconnected"
        )


# ============================================================
# PARSE COMMAND
# ============================================================

async def process_cli_command(
    command_line,
):

    parts = command_line.split()

    if not parts:
        return True

    command = parts[0].lower()

    # ========================================================
    # DEVICES
    # ========================================================

    if command == "devices":

        await request_devices()

        return True

    # ========================================================
    # REFRESH
    # ========================================================

    if command == "refresh":

        await request_devices()

        return True

    # ========================================================
    # INFO <device_id>
    # ========================================================

    if command == "info":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  info <device_id>"
            )

            return True

        device_id = parts[1]

        await send_command(
            device_id,
            "device_info",
        )

        return True

    # ========================================================
    # BATTERY <device_id>
    # ========================================================

    if command == "battery":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  battery <device_id>"
            )

            return True

        device_id = parts[1]

        await send_command(
            device_id,
            "battery_status",
        )

        return True

    # ========================================================
    # STATUS <device_id>
    # ========================================================

    if command == "status":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  status <device_id>"
            )

            return True

        device_id = parts[1]

        await send_command(
            device_id,
            "connection_status",
        )

        return True

    # ========================================================
    # LOCATION <device_id>
    # ========================================================

    if command == "location":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  location <device_id>"
            )

            return True

        device_id = parts[1]

        await send_command(
            device_id,
            "location_request",
        )

        return True

    # ========================================================
    # SCREEN-START
    # ========================================================

    if command == "screen-start":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  screen-start <device_id>"
            )

            return True

        print(
            "[INFO] Screen capture must "
            "be started through the "
            "Android app's local consent UI."
        )

        return True

    # ========================================================
    # SCREEN-STOP
    # ========================================================

    if command == "screen-stop":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  screen-stop <device_id>"
            )

            return True

        print(
            "[INFO] Screen capture is "
            "controlled by the Android "
            "app's local consent flow."
        )

        return True

    # ========================================================
    # MICROPHONE-START
    # ========================================================

    if command == "microphone-start":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  microphone-start <device_id>"
            )

            return True

        print(
            "[INFO] Microphone capture "
            "requires explicit local "
            "Android consent."
        )

        return True

    # ========================================================
    # MICROPHONE-STOP
    # ========================================================

    if command == "microphone-stop":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  microphone-stop <device_id>"
            )

            return True

        print(
            "[INFO] Microphone capture "
            "is controlled locally."
        )

        return True

    # ========================================================
    # CAMERA-START
    # ========================================================

    if command == "camera-start":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  camera-start <device_id>"
            )

            return True

        print(
            "[INFO] Camera capture "
            "requires explicit local "
            "Android consent."
        )

        return True

    # ========================================================
    # CAMERA-STOP
    # ========================================================

    if command == "camera-stop":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  camera-stop <device_id>"
            )

            return True

        print(
            "[INFO] Camera capture "
            "is controlled locally."
        )

        return True

    # ========================================================
    # CAMERA FRONT
    # ========================================================

    if command == "camera-front":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  camera-front <device_id>"
            )

            return True

        print(
            "[INFO] Camera selection "
            "requires the Android app's "
            "authorized camera session."
        )

        return True

    # ========================================================
    # CAMERA BACK
    # ========================================================

    if command == "camera-back":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  camera-back <device_id>"
            )

            return True

        print(
            "[INFO] Camera selection "
            "requires the Android app's "
            "authorized camera session."
        )

        return True

    # ========================================================
    # CAMERA SWITCH
    # ========================================================

    if command == "camera-switch":

        if len(parts) != 2:

            print(
                "Usage:"
            )

            print(
                "  camera-switch <device_id>"
            )

            return True

        print(
            "[INFO] Camera switching "
            "requires the Android app's "
            "authorized camera session."
        )

        return True

    # ========================================================
    # CAMERA INTERVAL
    # ========================================================

    if command == "camera-interval":

        if len(parts) != 3:

            print(
                "Usage:"
            )

            print(
                "  camera-interval "
                "<device_id> <seconds>"
            )

            return True

        device_id = parts[1]

        try:

            seconds = float(
                parts[2]
            )

            if seconds <= 0:

                raise ValueError

        except ValueError:

            print(
                "Interval must be "
                "greater than 0."
            )

            return True

        # The interval is deliberately
        # a PC-side setting, not an
        # Android capture instruction.
        print(
            f"[INFO] Snapshot interval "
            f"for {device_id} would be "
            f"set to {seconds:g}s in the "
            f"PC-side authorized camera "
            f"viewer."
        )

        return True

    # ========================================================
    # CLEAR
    # ========================================================

    if command == "clear":

        import os

        os.system(
            "cls"
            if os.name == "nt"
            else "clear"
        )

        return True

    # ========================================================
    # EXIT
    # ========================================================

    if command in {
        "exit",
        "quit",
    }:

        return False

    # ========================================================
    # HELP
    # ========================================================

    if command in {
        "help",
        "?",
    }:

        print_help()

        return True

    # ========================================================
    # UNKNOWN
    # ========================================================

    print(
        f"Unknown command: "
        f"{command}"
    )

    print(
        "Type 'help' for commands."
    )

    return True


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
        "Media commands require "
        "explicit local Android consent."
    )

    print()


# ============================================================
# CLI LOOP
# ============================================================

async def command_loop():

    print()

    print(
        "================================"
    )

    print(
        "      JARVIS CLOUD CONTROLLER"
    )

    print(
        "================================"
    )

    print_help()

    while True:

        try:

            command_line = await asyncio.to_thread(
                input,
                "JARVIS> ",
            )

        except (
            EOFError,
            KeyboardInterrupt,
        ):

            return

        command_line = command_line.strip()

        if not command_line:
            continue

        keep_running = await process_cli_command(
            command_line
        )

        if not keep_running:
            return


# ============================================================
# MAIN
# ============================================================

async def main():

    command_task = asyncio.create_task(
        command_loop()
    )

    while not command_task.done():

        if not connected:

            await connect_to_render()

            if command_task.done():
                break

            print(
                f"[RENDER] "
                f"Reconnecting in "
                f"{RECONNECT_DELAY}s..."
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )

        else:

            await asyncio.sleep(
                0.5
            )

    if not command_task.done():

        command_task.cancel()

        try:

            await command_task

        except asyncio.CancelledError:

            pass


# ============================================================
# ENTRY POINT
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