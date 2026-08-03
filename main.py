#!/usr/bin/env python3
"""
VDOT Server – Reverse proxy for VLESS/WS + SOCKS5 (VDOT‑ready).
VLESS link now includes explicit SNI.
"""
import asyncio, os, struct, logging, sys
import websockets
from websockets.exceptions import ConnectionClosed

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("vdot-py")

MAIN_PORT = int(os.environ.get("PORT", "8080"))
XRAY_PORT = int(os.environ.get("XRAY_PORT", "8081"))
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "10001"))

UUID = os.environ.get("UUID")
if not UUID:
    import uuid as _uu
    UUID = str(_uu.uuid4())
PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")

# VLESS link with explicit sni
VLESS_LINK = (
    f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
    f"?path=%2Fvless-ws&security=tls&type=ws"
    f"&host={PUBLIC_DOMAIN}"
    f"&sni={PUBLIC_DOMAIN}"
    f"&fp=randomized"
    f"#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
)

# ---------- WebSocket proxy to Xray (only connection argument) ----------
async def proxy_ws(websocket):
    logger.info("🔌 WS proxy: client connected, proxying to Xray")
    try:
        async with websockets.connect(f"ws://127.0.0.1:{XRAY_PORT}/vless-ws") as target:
            logger.info("🔗 WS proxy: connected to Xray, starting relay")
            async def forward(src, dest, tag):
                try:
                    async for msg in src:
                        await dest.send(msg)
                except ConnectionClosed:
                    logger.info(f"🔒 {tag}: connection closed")
                except Exception as e:
                    logger.error(f"❌ {tag}: {e}")
            await asyncio.gather(
                forward(websocket, target, "client->Xray"),
                forward(target, websocket, "Xray->client")
            )
    except Exception as e:
        logger.error(f"🔥 WS proxy: {e}")
        await websocket.close(1011, "Backend error")

# ---------- HTTP request handler ----------
async def process_http_request(connection, request):
    logger.info(f"🌐 HTTP: {request.path}")
    if request.path == "/vless-ws":
        return None  # Allow WebSocket upgrade
    return (200, {"Content-Type": "text/plain"}, b"VDOT Active")

# ---------- SOCKS5 server ----------
async def socks5_handler(reader, writer):
    try:
        ver, nmethods = await reader.readexactly(2)
        if ver != 5: writer.close(); return
        await reader.readexactly(nmethods)
        writer.write(b'\x05\x00'); await writer.drain()
        ver, cmd, rsv, atype = await reader.readexactly(4)
        if cmd != 1:
            writer.write(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00'); await writer.drain()
            writer.close(); return
        if atype == 1:
            addr = await reader.readexactly(4); dst_addr = '.'.join(map(str, addr))
        elif atype == 3:
            length = (await reader.readexactly(1))[0]
            addr = await reader.readexactly(length); dst_addr = addr.decode()
        elif atype == 4:
            addr = await reader.readexactly(16)
            dst_addr = ':'.join(f'{addr[i]:02x}{addr[i+1]:02x}' for i in range(0,16,2))
        else: writer.close(); return
        port_bytes = await reader.readexactly(2); dst_port = struct.unpack('!H', port_bytes)[0]
        logger.info(f"🧦 SOCKS5: {dst_addr}:{dst_port}")
        try:
            r_reader, r_writer = await asyncio.open_connection(dst_addr, dst_port)
        except Exception as e:
            logger.error(f"🧦 SOCKS5 fail: {e}")
            writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00'); await writer.drain()
            writer.close(); return
        writer.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00'); await writer.drain()
        async def relay(fr, to, name):
            try:
                while True:
                    data = await fr.read(4096)
                    if not data: break
                    to.write(data); await to.drain()
            except: pass
            finally: to.close()
        await asyncio.gather(relay(reader, r_writer, "c->r"), relay(r_reader, writer, "r->c"))
    except Exception as e:
        logger.error(f"🧦 SOCKS5 error: {e}")
        writer.close()

async def main():
    socks_server = await asyncio.start_server(socks5_handler, "0.0.0.0", SOCKS_PORT)
    ws_server = websockets.serve(proxy_ws, "0.0.0.0", MAIN_PORT, process_request=process_http_request)
    logger.info(f"🚀 SOCKS5 on {SOCKS_PORT} | WS proxy on {MAIN_PORT}")
    logger.info("=" * 50)
    logger.info("VLESS Link (copy to v2rayNG):")
    logger.info(VLESS_LINK)
    logger.info("=" * 50)
    await asyncio.gather(ws_server, socks_server.serve_forever())

if __name__ == "__main__":
    asyncio.run(main())
