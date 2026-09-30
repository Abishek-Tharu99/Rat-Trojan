from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
from typing import Dict
import asyncio
import secrets


app = FastAPI(
    title="JARVIS Cloud Server",
    version="1.0"
)


# ============================================================
# CONFIG
# ============================================================

LAB_SECRET = "LAB-123456"


# ============================================================
# DEVICE REGISTRY
# ============================================================

class DeviceConnection:

    def __init__(
        self,
        device_id: str,
        device_type: str,
        websocket: WebSocket
    ):
        self.device_id = device_id
        self.device_type = device_type
        self.websocket = websocket

        self.connected_at = datetime.now(timezone.utc)
        self.last_seen = datetime.now(timezone.utc)

        self.metadata = {}


devices: Dict[str, DeviceConnection] = {}


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()


async def send_json(
    websocket: WebSocket,
    message: dict
):
    await websocket.send_json(message)


async def send_to_device(
    device_id: str,
    message: dict
):

    device = devices.get(device_id)

    if device is None:
        print(
            f"ROUTER: device not connected: {device_id}"
        )
        return False

    try:

        await device.websocket.send_json(message)

        device.last_seen = datetime.now(timezone.utc)

        return True

    except Exception as e:

        print(
            f"ROUTER: send failed "
            f"{device_id}: {e}"
        )

        return False


def remove_device(
    device_id: str,
    websocket: WebSocket
):

    device = devices.get(device_id)

    if device is not None:

        if device.websocket is websocket:

            del devices[device_id]

            print(
                f"DEVICE REMOVED: "
                f"{device_id}"
            )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
async def root():

    return {
        "service": "JARVIS Cloud Server",
        "status": "online",
        "time": utc_now(),
        "connected_devices": len(devices)
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    return {
        "status": "healthy",
        "time": utc_now(),
        "devices": len(devices)
    }


# ============================================================
# DEVICE LIST
# ============================================================

@app.get("/devices")
async def get_devices():

    result = []

    for device in devices.values():

        result.append({
            "device_id": device.device_id,
            "device_type": device.device_type,
            "connected_at":
                device.connected_at.isoformat(),
            "last_seen":
                device.last_seen.isoformat(),
            "metadata":
                device.metadata
        })

    return {
        "count": len(result),
        "devices": result
    }


# ============================================================
# WEBSOCKET
# ============================================================

@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket
):

    await websocket.accept()

    print(
        "WEBSOCKET: connection accepted"
    )

    device_id = None
    device_type = None

    try:

        # ----------------------------------------------------
        # Initial server message
        # ----------------------------------------------------

        await send_json(
            websocket,
            {
                "type": "connected",
                "message":
                    "Connected to JARVIS Cloud Server",
                "server_time":
                    utc_now()
            }
        )


        # ----------------------------------------------------
        # MESSAGE LOOP
        # ----------------------------------------------------

        while True:

            message = await websocket.receive()

            # =================================================
            # TEXT / JSON MESSAGE
            # =================================================

            if "text" in message:

                import json

                try:

                    data = json.loads(
                        message["text"]
                    )

                except Exception:

                    await send_json(
                        websocket,
                        {
                            "type": "error",
                            "message":
                                "Invalid JSON"
                        }
                    )

                    continue


                message_type = data.get(
                    "type"
                )


                print(
                    f"RECEIVED: "
                    f"{message_type}"
                )


                # =============================================
                # PAIR REQUEST
                # =============================================

                if message_type == "pair_request":

                    requested_device_id = data.get(
                        "device_id"
                    )

                    requested_device_type = data.get(
                        "device_type"
                    )

                    secret = data.get(
                        "secret"
                    )


                    if not requested_device_id:

                        await send_json(
                            websocket,
                            {
                                "type": "pair_response",
                                "success": False,
                                "message":
                                    "Missing device_id"
                            }
                        )

                        continue


                    if not secrets.compare_digest(
                        str(secret or ""),
                        LAB_SECRET
                    ):

                        print(
                            "PAIRING FAILED: "
                            f"{requested_device_id}"
                        )

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "pair_response",
                                "success": False,
                                "message":
                                    "Invalid lab secret"
                            }
                        )

                        continue


                    device_id = requested_device_id

                    device_type = (
                        requested_device_type
                        or "unknown"
                    )


                    # Replace an old connection
                    # belonging to the same device.
                    old_device = devices.get(
                        device_id
                    )

                    if old_device is not None:

                        try:

                            await old_device.websocket.close()

                        except Exception:

                            pass


                    connection = DeviceConnection(
                        device_id=device_id,
                        device_type=device_type,
                        websocket=websocket
                    )

                    devices[device_id] = connection


                    print(
                        f"DEVICE PAIRED: "
                        f"{device_id} "
                        f"({device_type})"
                    )


                    await send_json(
                        websocket,
                        {
                            "type":
                                "pair_response",
                            "success": True,
                            "device_id":
                                device_id,
                            "server_time":
                                utc_now()
                        }
                    )


                # =============================================
                # HEARTBEAT
                # =============================================

                elif message_type == "heartbeat":

                    if device_id:

                        device = devices.get(
                            device_id
                        )

                        if device:

                            device.last_seen = (
                                datetime.now(
                                    timezone.utc
                                )
                            )


                    await send_json(
                        websocket,
                        {
                            "type":
                                "heartbeat_ack",
                            "time":
                                utc_now()
                        }
                    )


                # =============================================
                # DEVICE INFO
                # =============================================

                elif message_type == "device_info":

                    if not device_id:

                        await send_json(
                            websocket,
                            {
                                "type": "error",
                                "message":
                                    "Device not paired"
                            }
                        )

                        continue


                    device = devices.get(
                        device_id
                    )

                    if device:

                        metadata = data.get(
                            "data",
                            {}
                        )

                        device.metadata = metadata

                        print(
                            f"DEVICE INFO: "
                            f"{device_id}"
                        )


                    # Tell PC/JARVIS later
                    await route_to_pc(
                        {
                            "type":
                                "device_info",
                            "device_id":
                                device_id,
                            "data":
                                data.get(
                                    "data",
                                    {}
                                )
                        }
                    )


                # =============================================
                # LOCATION
                # =============================================

                elif message_type == "location":

                    if not device_id:

                        await send_json(
                            websocket,
                            {
                                "type": "error",
                                "message":
                                    "Device not paired"
                            }
                        )

                        continue


                    location_data = data.get(
                        "data",
                        {}
                    )


                    print(
                        f"LOCATION FROM "
                        f"{device_id}: "
                        f"{location_data}"
                    )


                    await route_to_pc(
                        {
                            "type":
                                "location",
                            "device_id":
                                device_id,
                            "data":
                                location_data
                        }
                    )


                # =============================================
                # COMMAND RESPONSE
                # =============================================

                elif message_type == "command_response":

                    if not device_id:

                        continue


                    command_id = data.get(
                        "command_id"
                    )


                    response_data = data.get(
                        "data"
                    )


                    print(
                        f"COMMAND RESPONSE "
                        f"FROM {device_id}: "
                        f"{command_id}"
                    )


                    await route_to_pc(
                        {
                            "type":
                                "command_response",
                            "device_id":
                                device_id,
                            "command_id":
                                command_id,
                            "data":
                                response_data
                        }
                    )


                # =============================================
                # PC REGISTER
                # =============================================

                elif message_type == "pc_register":

                    requested_device_id = data.get(
                        "device_id"
                    )

                    secret = data.get(
                        "secret"
                    )


                    if not secrets.compare_digest(
                        str(secret or ""),
                        LAB_SECRET
                    ):

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "pc_register_response",
                                "success": False,
                                "message":
                                    "Invalid lab secret"
                            }
                        )

                        continue


                    device_id = (
                        requested_device_id
                        or "jarvis-pc"
                    )

                    device_type = "pc"


                    devices[device_id] = (
                        DeviceConnection(
                            device_id=device_id,
                            device_type=device_type,
                            websocket=websocket
                        )
                    )


                    print(
                        f"PC REGISTERED: "
                        f"{device_id}"
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


                # =============================================
                # COMMAND FROM PC
                # =============================================

                elif message_type == "command":

                    if device_type != "pc":

                        await send_json(
                            websocket,
                            {
                                "type": "error",
                                "message":
                                    "Only PC/JARVIS "
                                    "can send cloud "
                                    "commands"
                            }
                        )

                        continue


                    target_device = data.get(
                        "device_id"
                    )

                    command_id = data.get(
                        "command_id"
                    )

                    command = data.get(
                        "command"
                    )


                    if not target_device:

                        await send_json(
                            websocket,
                            {
                                "type": "error",
                                "message":
                                    "Missing target device"
                            }
                        )

                        continue


                    success = await send_to_device(
                        target_device,
                        {
                            "type":
                                "command",
                            "command_id":
                                command_id,
                            "command":
                                command
                        }
                    )


                    if not success:

                        await send_json(
                            websocket,
                            {
                                "type":
                                    "command_error",
                                "command_id":
                                    command_id,
                                "device_id":
                                    target_device,
                                "message":
                                    "Target device "
                                    "not connected"
                            }
                        )


                # =============================================
                # UNKNOWN MESSAGE
                # =============================================

                else:

                    await send_json(
                        websocket,
                        {
                            "type":
                                "error",
                            "message":
                                "Unknown message type",
                            "received":
                                message_type
                        }
                    )


            # =================================================
            # BINARY MESSAGE
            # =================================================

            elif "bytes" in message:

                binary_data = message["bytes"]

                if not device_id:

                    print(
                        "BINARY: rejected "
                        "(device not paired)"
                    )

                    continue


                if len(binary_data) < 1:

                    continue


                packet_type = binary_data[0]

                payload = binary_data[1:]


                # =============================================
                # SCREEN
                # =============================================

                if packet_type == 0x01:

                    print(
                        f"SCREEN: "
                        f"{device_id} "
                        f"{len(payload)} bytes"
                    )

                    await route_binary_to_pc(
                        device_id,
                        0x01,
                        payload
                    )


                # =============================================
                # MICROPHONE
                # =============================================

                elif packet_type == 0x02:

                    print(
                        f"MICROPHONE: "
                        f"{device_id} "
                        f"{len(payload)} bytes"
                    )

                    await route_binary_to_pc(
                        device_id,
                        0x02,
                        payload
                    )


                # =============================================
                # CAMERA
                # =============================================

                elif packet_type == 0x03:

                    print(
                        f"CAMERA: "
                        f"{device_id} "
                        f"{len(payload)} bytes"
                    )

                    await route_binary_to_pc(
                        device_id,
                        0x03,
                        payload
                    )


                else:

                    print(
                        f"BINARY: unknown "
                        f"packet type "
                        f"{packet_type}"
                    )


    except WebSocketDisconnect:

        print(
            f"WEBSOCKET DISCONNECTED: "
            f"{device_id}"
        )


    except Exception as e:

        print(
            f"WEBSOCKET ERROR: "
            f"{e}"
        )


    finally:

        if device_id:

            remove_device(
                device_id,
                websocket
            )


# ============================================================
# PC ROUTING HELPERS
# ============================================================

async def route_to_pc(
    message: dict
):

    pc_devices = [
        device
        for device in devices.values()
        if device.device_type == "pc"
    ]


    for pc in pc_devices:

        try:

            await pc.websocket.send_json(
                message
            )

            pc.last_seen = (
                datetime.now(
                    timezone.utc
                )
            )

        except Exception as e:

            print(
                f"PC ROUTE ERROR: {e}"
            )


async def route_binary_to_pc(
    device_id: str,
    packet_type: int,
    payload: bytes
):

    pc_devices = [
        device
        for device in devices.values()
        if device.device_type == "pc"
    ]


    if not pc_devices:

        print(
            "BINARY ROUTER: "
            "no PC connected"
        )

        return


    packet = (
        bytes([packet_type])
        + payload
    )


    for pc in pc_devices:

        try:

            await pc.websocket.send_bytes(
                packet
            )

        except Exception as e:

            print(
                f"BINARY PC ROUTE ERROR: "
                f"{e}"
            )