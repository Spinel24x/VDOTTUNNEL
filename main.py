#!/usr/bin/env python3
"""
VDOT Server – Reverse proxy (with debug logs) + SOCKS5 + self-test.
"""
import asyncio
import os
import struct
import logging
import sys
import websockets
from websockets.exceptions import ConnectionClosed

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("vdot-py")

MAIN_PORT = int(os.environ.get("PORT", "8080"))
XRAY_PORT = int(os.environ.get("XRAY_PORT", "8081"))
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "10001"))

UUID = os.environ.get("UUID")
if not UUID:
    import uuid as uuid_lib
    UUID = str(uuid_lib.uuid4())
PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")

VLESS_LINK = (
    f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
    f"?path=%2Fvless-ws&security=tls&type=ws&host={PUBLIC_DOMAIN}"
    f"&fp=chrome#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
)

# ---------- WebSocket proxy to Xray ----------
async def proxy_ws(websocket, path):
    logger.info(f"WS proxy: client connected, path={path}")
    try:
        logger.info(f"WS proxy: connecting to Xray at ws://127.0.0.1:{XRAY_PORT}/vless-ws")
        async with websockets.connect(f"ws://127.0.0.1:{XRAY_PORT}/vless-ws") as target:
            logger.info("WS proxy: connected to Xray, starting relay")
            async def client_to_target():
                try:
                    async for msg in websocket:
                        logger.debug(f"WS proxy: client->Xray {len(msg)} bytes")
                        await target.send(msg)
                except ConnectionClosed:
                    logger.info("WS proxy: client->Xray closed")
                except Exception as e:
                    logger.error(f"WS proxy: client->Xray error: {e}")
            async def target_to_client():
                try:
                    async for msg in target:
                        logger.debug(f"WS proxy: Xray->client {len(msg)} bytes")
                        await websocket.send(msg)
                except ConnectionClosed:
                    logger.info("WS proxy: Xray->client closed")
                except Exception as e:
                    logger.error(f"WS proxy: Xray->client error: {e}")
            await asyncio.gather(client_to_target(), target_to_client())
    except Exception as e:
        logger.error(f"WS proxy: cannot connect to Xray: {e}")
        await websocket.close(1011, "Backend error")

# ---------- HTTP request handler ----------
async def process_http_request(connection, request):
    logger.info(f"HTTP request: path={request.path}, headers={dict(request.headers)}")
    if request.path == "/vless-ws":
        logger.info("Allowing WebSocket upgrade for /vless-ws")
        return None
    body = b"VDOT Active"
    return (200, {"Content-Type": "text/plain"}, body)

# ---------- SOCKS5 server (with heavy logging) ----------
async def socks5_handler(reader, writer):
    peer = writer.get_extra_info('peername')
    logger.info(f"SOCKS5: new connection from {peer}")
    try:
        ver, nmethods = await reader.readexactly(2)
        logger.debug(f"SOCKS5: ver={ver}, nmethods={nmethods}")
        if ver != 5:
            writer.close(); return
        methods = await reader.readexactly(nmethods)
        writer.write(b'\x05\x00')
        await writer.drain()
        ver, cmd, rsv, atype = await reader.readexactly(4)
        logger.debug(f"SOCKS5: cmd={cmd}, atype={atype}")
        if cmd != 1:
            writer.write(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
            await writer.drain()
            writer.close(); return
        if atype == 1:
            addr = await reader.readexactly(4)
            dst_addr = '.'.join(map(str, addr))
        elif atype == 3:
            length = (await reader.readexactly(1))[0]
            addr = await reader.readexactly(length)
            dst_addr = addr.decode()
        elif atype == 4:
            addr = await reader.readexactly(16)
            dst_addr = ':'.join(f'{addr[i]:02x}{addr[i+1]:02x}' for i in range(0,16,2))
        else:
            writer.close(); return
        port_bytes = await reader.readexactly(2)
        dst_port = struct.unpack('!H', port_bytes)[0]
        logger.info(f"SOCKS5: connect to {dst_addr}:{dst_port}")
        try:
            remote_reader, remote_writer = await asyncio.open_connection(dst_addr, dst_port)
        except Exception as e:
            logger.error(f"SOCKS5: connection failed: {e}")
            writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
            await writer.drain()
            writer.close(); return
        writer.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
        await writer.drain()
        async def relay(from_, to_, name):
            try:
                while True:
                    data = await from_.read(4096)
                    if not data: break
                    logger.debug(f"SOCKS5: {name} {len(data)} bytes")
                    to_.write(data)
                    await to_.drain()
            except Exception as e:
                logger.debug(f"SOCKS5: {name} closed: {e}")
            finally:
                to_.close()
        await asyncio.gather(
            relay(reader, remote_writer, "client->remote"),
            relay(remote_reader, writer, "remote->client")
        )
    except Exception as e:
        logger.error(f"SOCKS5: error: {e}")
        writer.close()

# ---------- Self-test using SOCKS5 proxy ----------
async def self_test():
    try:
        logger.info("Self-test: attempting connection to checkip.amazonaws.com:80 via SOCKS5")
        # Simple SOCKS5 client using asyncio
        reader, writer = await asyncio.open_connection("127.0.0.1", SOCKS_PORT)
        # GREETING
        writer.write(b'\x05\x01\x00')  # version 5, 1 method, no auth
        await writer.drain()
        resp = await reader.readexactly(2)
        if resp != b'\x05\x00':
            logger.error("Self-test: SOCKS5 greeting failed")
            writer.close()
            return
        # CONNECT request to checkip.amazonaws.com:80
        host = "checkip.amazonaws.com"
        writer.write(b'\x05\x01\x00\x03' + bytes([len(host)]) + host.encode() + b'\x00\x50')  # port 80
        await writer.drain()
        resp = await reader.readexactly(10)
        if resp[1] != 0x00:
            logger.error(f"Self-test: SOCKS5 connect failed, code={resp[1]}")
            writer.close()
            return
        # Send HTTP GET
        writer.write(b"GET / HTTP/1.1\r\nHost: checkip.amazonaws.com\r\nConnection: close\r\n\r\n")
        await writer.drain()
        data = await reader.read(1024)
        logger.info(f"Self-test: response: {data.decode().strip()}")
        writer.close()
        logger.info("Self-test: SOCKS5 proxy is working correctly!")
    except Exception as e:
        logger.error(f"Self-test failed: {e}")

async def main():
    # Start SOCKS5
    socks_server = await asyncio.start_server(socks5_handler, "0.0.0.0", SOCKS_PORT)
    logger.info(f"SOCKS5 proxy on port {SOCKS_PORT}")

    # Start WS reverse proxy
    ws_server = websockets.serve(
        proxy_ws,
        "0.0.0.0",
        MAIN_PORT,
        process_request=process_http_request
    )
    logger.info(f"Reverse proxy on port {MAIN_PORT}")

    logger.info("=" * 50)
    logger.info("VLESS Link:")
    logger.info(VLESS_LINK)
    logger.info("=" * 50)

    # Run self-test after a short delay
    asyncio.create_task(self_test())

    await asyncio.gather(ws_server, socks_server.serve_forever())

if __name__ == "__main__":
    asyncio.run(main())
