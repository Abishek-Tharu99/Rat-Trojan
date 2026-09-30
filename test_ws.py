import json
import websocket

ws = websocket.create_connection(
    "wss://rat-trojan.onrender.com/ws"
)

print("CONNECTED")

message = ws.recv()
print("SERVER:", message)

ws.send(json.dumps({
    "type": "hello"
}))

message = ws.recv()
print("SERVER:", message)

ws.send(json.dumps({
    "type": "ping"
}))

message = ws.recv()
print("SERVER:", message)

ws.close()