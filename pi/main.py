import asyncio
import websockets
import zeroconf
import json
import threading

mac_ip = None
found = threading.Event()


class ServiceListener:
    def add_service(self, zc, type_, name):
        global mac_ip

        info = zc.get_service_info(type_, name)
        if info is None:
            return

        mac_ip = info.parsed_addresses()[0]
        found.set()

    def remove_service(self, zc, type_, name):
        pass

    def update_service(self, zc, type_, name):
        pass


async def connect_and_run():
    zc = zeroconf.Zeroconf()
    listener = ServiceListener()

    zeroconf.ServiceBrowser(zc, "_ws._tcp.local.", listener)

    await asyncio.get_running_loop().run_in_executor(None, found.wait, 30)
    if mac_ip is None:
        print("Mac not found on network")
        return

    print(f"Mac found at {mac_ip}")
    async with websockets.connect(f"ws://{mac_ip}:8765/ws") as ws:
        await ws.send(
            json.dumps({"type": "system.handshake", "payload": {"node": "pi"}})
        )
        async for message in ws:
            print(f"Received: {message}")


if __name__ == "__main__":
    asyncio.run(connect_and_run())
