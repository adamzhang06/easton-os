from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import uvicorn
import zeroconf  # pyrefly: ignore [missing-import]
import asyncio
import json
import socket


def register_mdns():

    # get the IP address of the mac
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    IP_ADDRESS = s.getsockname()[0]
    s.close()

    # create azeroconf service info
    info = zeroconf.ServiceInfo(
        type="_ws._tcp.local.",
        name="easton-brain._ws._tcp.local.",
        addresses=[socket.inet_aton(IP_ADDRESS)],
        port=8765,
    )

    # register the service and keep it alive by returning to main.py
    zc = zeroconf.Zeroconf()
    zc.register_service(info=info)
    return zc


app = FastAPI()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):

    await websocket.accept()
    print("Pi connected")

    # send handshake message
    await websocket.send_text(
        json.dumps({"type": "system.handshake_ack", "payload": {}})
    )

    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received message: {data}")
    except WebSocketDisconnect:
        print("Pi disconnected")


if __name__ == "__main__":
    zc = register_mdns()
    uvicorn.run(app, host="0.0.0.0", port=8765)

    # clean up after unvicorn exits
    zc.unregister_all_services()
    zc.close()
