#!/usr/bin/env python3
"""
VDOT Server – Reverse proxy for VLESS/WS + SOCKS5 (VDOT‑ready).
No web config – VLESS link is printed in logs.
"""
import asyncio
import os
import struct
import logging
import websockets
from websockets.exceptions import ConnectionClosed

logging.basicConfig(level=logging.INFO)
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
    f"&fp=randomized#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
)

# ---------- WebSocket proxy to Xray (FIXED: only connection argument) ----------
async def proxy_ws(websocket):
    """Forward WebSocket connection to Xray's VLESS inbound."""
    logger.info("WS proxy: client connected, proxying to Xray")
    try:
        async with websockets.connect(f"ws://127.0.0.1:{XRAY_PORT}/vless-ws") as target:
            logger.info("WS proxy: connected to Xray, starting relay")
            async def client_to_target():
                try:
                    async for msg in websocket:
                        await target.send(msg)
                except ConnectionClosed:
                    pass
                except Exception as e:
                    logger.error(f"WS proxy: client->Xray error: {e}")
            async def target_to_client():
                try:
                    async for msg in target:
                        await websocket.send(msg)
                except ConnectionClosed:
                    pass
                except Exception as e:
                    logger.error(f"WS proxy: Xray->client error: {e}")
            await asyncio.gather(client_to_target(), target_to_client())
    except Exception as e:
        logger.error(f"WS proxy: cannot connect to Xray: {e}")
        await websocket.close(1011, "Backend error")

# ---------- HTTP request handler (no config page) ----------
async def process_http_request(connection, request):
    """Allow WebSocket upgrade only on /vless-ws, else simple text."""
    logger.info(f"HTTP request: path={request.path}")
    if request.path == "/vless-ws":
        # Let WebSocket handshake proceed – connection will be passed to proxy_ws
        return None
    body = b"VDOT Tunnel Active - use VLESS client."
    return (200, {"Content-Type": "text/plain"}, body)

# ---------- SOCKS5 server (unchanged) ----------
async def socks5_handler(reader, writer):
    try:
        ver, nmethods = await reader.readexactly(2)
        if ver != 5:
            writer.close(); return
        methods = await reader.readexactly(nmethods)
        writer.write(b'\x05\x00')
        await writer.drain()
        ver, cmd, rsv, atype = await reader.readexactly(4)
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
        logger.info(f"SOCKS5 connect to {dst_addr}:{dst_port}")
        try:
            remote_reader, remote_writer = await asyncio.open_connection(dst_addr, dst_port)
        except Exception as e:
            logger.error(f"SOCKS5 connection failed: {e}")
            writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
            await writer.drain()
            writer.close(); return
        writer.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
        await writer.drain()
        async def client_to_remote():
            try:
                while True:
                    data = await reader.read(4096)
                    if not data: break
                    remote_writer.write(data)
                    await remote_writer.drain()
            except: pass
            finally: remote_writer.close()
        async def remote_to_client():
            try:
                while True:
                    data = await remote_reader.read(4096)
                    if not data: break
                    writer.write(data)
                    await writer.drain()
            except: pass
            finally: writer.close()
        await asyncio.gather(client_to_remote(), remote_to_client())
    except Exception as e:
        logger.error(f"SOCKS5 error: {e}")
        writer.close()

async def main():
    # Start SOCKS5 server
    socks_server = await asyncio.start_server(socks5_handler, "0.0.0.0", SOCKS_PORT)
    logger.info(f"SOCKS5 proxy on port {SOCKS_PORT}")

    # Start WebSocket reverse proxy (handler is just 'proxy_ws' without path)
    ws_server = websockets.serve(
        proxy_ws,
        "0.0.0.0",
        MAIN_PORT,
        process_request=process_http_request
    )
    logger.info(f"Reverse proxy on port {MAIN_PORT}")

    # Print VLESS link to logs
    logger.info("=" * 50)
    logger.info("VLESS Link (copy to v2rayNG):")
    logger.info(VLESS_LINK)
    logger.info("=" * 50)

    await asyncio.gather(ws_server, socks_server.serve_forever())

if __name__ == "__main__":
    asyncio.run(main())
