from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone

app = FastAPI(title="JARVIS Cloud Server")


@app.get("/")
async def root():
    return {
        "service": "JARVIS Cloud Server",
        "status": "online",
        "time": datetime.now(timezone.utc).isoformat()
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy"
    }


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()

    print("WebSocket client connected")

    await websocket.send_json({
        "type": "connected",
        "message": "Connected to JARVIS Cloud Server"
    })

    try:

        while True:

            message = await websocket.receive_json()

            print("Received:", message)

            message_type = message.get("type")

            if message_type == "ping":

                await websocket.send_json({
                    "type": "pong",
                    "time": datetime.now(
                        timezone.utc
                    ).isoformat()
                })

            elif message_type == "hello":

                await websocket.send_json({
                    "type": "hello_response",
                    "message": "Hello from Render!"
                })

            else:

                await websocket.send_json({
                    "type": "error",
                    "message": "Unknown message type"
                })

    except WebSocketDisconnect:

        print("WebSocket client disconnected")