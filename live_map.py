import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HOST = "127.0.0.1"
PORT = 8766


HTML = r"""
<!DOCTYPE html>
<html>
<head>

<meta charset="utf-8">

<title>JARVIS Live Location</title>

<meta
    name="viewport"
    content="width=device-width, initial-scale=1.0"
/>

<link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
/>

<style>

html,
body {

    margin: 0;
    padding: 0;

    width: 100%;
    height: 100%;

    overflow: hidden;

    font-family:
        Arial,
        sans-serif;
}

#map {

    width: 100%;
    height: 100%;
}

#status {

    position: absolute;

    z-index: 1000;

    top: 15px;
    left: 15px;

    background: rgba(20, 20, 20, 0.90);

    color: white;

    padding: 12px 16px;

    border-radius: 8px;

    min-width: 230px;

    box-shadow:
        0 2px 10px rgba(0,0,0,0.35);
}

#status-title {

    font-weight: bold;

    margin-bottom: 7px;
}

#status-data {

    font-size: 13px;

    line-height: 1.5;

    color: #cccccc;
}

#live {

    display: inline-block;

    width: 9px;
    height: 9px;

    border-radius: 50%;

    background: #777;

    margin-right: 6px;
}

</style>

</head>

<body>

<div id="map"></div>

<div id="status">

    <div id="status-title">

        <span id="live"></span>

        JARVIS LIVE LOCATION

    </div>

    <div id="status-data">

        Waiting for location...

    </div>

</div>

<script
    src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js">
</script>

<script>

const DEFAULT_LAT = 27.7172;
const DEFAULT_LON = 85.3240;
const DEFAULT_ZOOM = 13;


// ============================================================
// MAP
// ============================================================

const map = L.map("map").setView(
    [
        DEFAULT_LAT,
        DEFAULT_LON
    ],
    DEFAULT_ZOOM
);


// ============================================================
// OPENSTREETMAP
// ============================================================

L.tileLayer(

    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",

    {

        maxZoom: 19,

        attribution:
            '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'

    }

).addTo(map);


// ============================================================
// MARKERS
// ============================================================

const markers = {};

const circles = {};


// ============================================================
// MAP STATE
// ============================================================

let firstLocation = true;

let followDevice = true;


// ============================================================
// UPDATE STATUS
// ============================================================

function updateStatus(
    location
) {

    const live = document.getElementById(
        "live"
    );

    const statusData = document.getElementById(
        "status-data"
    );

    live.style.background =
        "#00ff88";

    const accuracy =
        location.accuracy !== null &&
        location.accuracy !== undefined

        ? Number(location.accuracy).toFixed(1)
        : "unknown";

    const speed =
        location.speed !== null &&
        location.speed !== undefined

        ? Number(location.speed).toFixed(1)
        : "unknown";

    statusData.innerHTML =

        "<b>Device:</b> "
        +
        escapeHtml(
            location.device_id
        )

        +

        "<br>"

        +

        "<b>Latitude:</b> "
        +
        Number(location.latitude).toFixed(6)

        +

        "<br>"

        +

        "<b>Longitude:</b> "
        +
        Number(location.longitude).toFixed(6)

        +

        "<br>"

        +

        "<b>Accuracy:</b> "
        +
        accuracy
        +
        " m"

        +

        "<br>"

        +

        "<b>Speed:</b> "
        +
        speed
        +
        " m/s";
}


// ============================================================
// ESCAPE HTML
// ============================================================

function escapeHtml(
    value
) {

    return String(value)

        .replace(
            /&/g,
            "&amp;"
        )

        .replace(
            /</g,
            "&lt;"
        )

        .replace(
            />/g,
            "&gt;"
        )

        .replace(
            /"/g,
            "&quot;"
        )

        .replace(
            /'/g,
            "&#039;"
        );
}


// ============================================================
// UPDATE DEVICE
// ============================================================

function updateDevice(
    location
) {

    if (
        location.latitude === null ||
        location.longitude === null
    ) {

        return;
    }


    const deviceId =
        location.device_id;


    const lat =
        Number(location.latitude);


    const lon =
        Number(location.longitude);


    const accuracy =
        Number(location.accuracy || 0);


    const position = [
        lat,
        lon
    ];


    // ========================================================
    // MARKER
    // ========================================================

    if (
        !markers[deviceId]
    ) {

        markers[deviceId] =
            L.marker(
                position
            ).addTo(
                map
            );

        markers[deviceId].bindPopup(
            "<b>"
            +
            escapeHtml(
                deviceId
            )
            +
            "</b>"
        );

    } else {

        markers[deviceId].setLatLng(
            position
        );
    }


    // ========================================================
    // ACCURACY CIRCLE
    // ========================================================

    if (
        !circles[deviceId]
    ) {

        circles[deviceId] =
            L.circle(

                position,

                {

                    radius:
                        accuracy,

                    color:
                        "#3388ff",

                    fillColor:
                        "#3388ff",

                    fillOpacity:
                        0.15

                }

            ).addTo(
                map
            );

    } else {

        circles[deviceId].setLatLng(
            position
        );

        circles[deviceId].setRadius(
            accuracy
        );
    }


    // ========================================================
    // CENTER MAP
    // ========================================================

    if (
        firstLocation ||
        followDevice
    ) {

        map.setView(
            position,
            Math.max(
                map.getZoom(),
                15
            )
        );

        firstLocation = false;
    }


    // ========================================================
    // STATUS
    // ========================================================

    updateStatus(
        location
    );
}


// ============================================================
// GET LOCATION DATA
// ============================================================

async function pollLocation() {

    try {

        const response =
            await fetch(
                "/location"
            );

        if (
            !response.ok
        ) {

            throw new Error(
                "HTTP "
                +
                response.status
            );
        }

        const location =
            await response.json();


        if (
            location &&
            location.device_id
        ) {

            updateDevice(
                location
            );
        }

    } catch (
        error
    ) {

        console.log(
            "Location polling error:",
            error
        );
    }
}


// ============================================================
// FOLLOW BUTTON
// ============================================================

const followControl =
    L.control(
        {
            position:
                "topright"
        }
    );


followControl.onAdd =
    function() {

        const div =
            L.DomUtil.create(
                "div"
            );

        div.style.background =
            "white";

        div.style.padding =
            "6px 10px";

        div.style.borderRadius =
            "5px";

        div.style.cursor =
            "pointer";

        div.innerHTML =
            "Follow: ON";


        div.onclick =
            function() {

                followDevice =
                    !followDevice;

                div.innerHTML =
                    "Follow: "
                    +
                    (
                        followDevice
                        ? "ON"
                        : "OFF"
                    );
            };


        L.DomEvent.disableClickPropagation(
            div
        );


        return div;
    };


followControl.addTo(
    map
);


// ============================================================
// POLL EVERY 2 SECONDS
// ============================================================

pollLocation();

setInterval(
    pollLocation,
    2000
);

</script>

</body>
</html>
"""


# ============================================================
# LOCATION STORE
# ============================================================

latest_location = None

location_lock = threading.Lock()


# ============================================================
# UPDATE LOCATION
# ============================================================

def set_location(
    location
):

    global latest_location

    if not isinstance(
        location,
        dict
    ):

        return

    if (
        location.get(
            "latitude"
        )
        is None
    ):

        return

    if (
        location.get(
            "longitude"
        )
        is None
    ):

        return

    with location_lock:

        latest_location = dict(
            location
        )


# ============================================================
# GET LOCATION
# ============================================================

def get_location():

    with location_lock:

        if latest_location is None:

            return None

        return dict(
            latest_location
        )


# ============================================================
# HTTP HANDLER
# ============================================================

class MapHandler(
    BaseHTTPRequestHandler
):

    def log_message(
        self,
        format,
        *args
    ):

        # Keep HTTP polling quiet.
        return


    def do_GET(
        self
    ):

        # ----------------------------------------------------
        # MAP
        # ----------------------------------------------------

        if self.path == "/":

            body = HTML.encode(
                "utf-8"
            )

            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "text/html; charset=utf-8"
            )

            self.send_header(
                "Content-Length",
                str(
                    len(body)
                )
            )

            self.end_headers()

            self.wfile.write(
                body
            )

            return


        # ----------------------------------------------------
        # LOCATION
        # ----------------------------------------------------

        if self.path == "/location":

            location =get_location()

            if location is None:

                body = b"{}"

            else:

                body = json.dumps(
                    location
                ).encode(
                    "utf-8"
                )


            self.send_response(
                200
            )

            self.send_header(
                "Content-Type",
                "application/json"
            )

            self.send_header(
                "Cache-Control",
                "no-cache"
            )

            self.send_header(
                "Content-Length",
                str(
                    len(body)
                )
            )

            self.end_headers()

            self.wfile.write(
                body
            )

            return


        # ----------------------------------------------------
        # NOT FOUND
        # ----------------------------------------------------

        self.send_response(
            404
        )

        self.end_headers()


# ============================================================
# START SERVER
# ============================================================

def start_map_server():

    server = ThreadingHTTPServer(

        (
            HOST,
            PORT
        ),

        MapHandler
    )

    thread = threading.Thread(

        target=
            server.serve_forever,

        daemon=True
    )

    thread.start()

    print(
        "[MAP] Live map server started."
    )

    print(
        f"[MAP] http://{HOST}:{PORT}"
    )

    return server


# ============================================================
# OPEN MAP
# ============================================================

def open_map():

    import webbrowser

    webbrowser.open(
        f"http://{HOST}:{PORT}"
    )