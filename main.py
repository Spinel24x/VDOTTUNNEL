#!/usr/bin/env python3
"""VDOT Server – HTTP config page + SOCKS5 proxy (VDOT‑ready)."""
import asyncio, os, struct, logging, sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("vdot-py")

HTTP_PORT = int(os.environ.get("HTTP_PORT", "10000"))
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "10001"))

UUID = os.environ.get("UUID")
if not UUID:
    import uuid as _uu
    UUID = str(_uu.uuid4())
PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")

VLESS_LINK = (
    f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
    f"?path=%2Fvless-ws&security=tls&type=ws"
    f"&host={PUBLIC_DOMAIN}"
    f"&sni={PUBLIC_DOMAIN}"
    f"&fp=randomized"
    f"#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
)

HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>VDOT</title></head>
<body style="font-family:sans-serif;max-width:600px;margin:50px auto">
<h1>🚀 VDOT Tunnel</h1>
<p>Copy the link below into <b>v2rayNG</b>:</p>
<textarea rows="3" style="width:100%;">{VLESS_LINK}</textarea>
<p><b>UUID:</b> {UUID}<br><b>Domain:</b> {PUBLIC_DOMAIN}<br><b>Path:</b> /vless-ws</p>
</body></html>"""
HTML_BODY = HTML.encode()

async def http_handler(reader, writer):
    resp = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(HTML_BODY)}\r\nConnection: close\r\n\r\n".encode() + HTML_BODY
    writer.write(resp)
    await writer.drain()
    writer.close()

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
            addr = await reader.readexactly(4); dst = '.'.join(map(str, addr))
        elif atype == 3:
            length = (await reader.readexactly(1))[0]
            addr = await reader.readexactly(length); dst = addr.decode()
        elif atype == 4:
            addr = await reader.readexactly(16)
            dst = ':'.join(f'{addr[i]:02x}{addr[i+1]:02x}' for i in range(0,16,2))
        else: writer.close(); return
        port = struct.unpack('!H', await reader.readexactly(2))[0]
        logger.info(f"Socks5 connect {dst}:{port}")
        try:
            rr, rw = await asyncio.open_connection(dst, port)
        except Exception as e:
            logger.error(f"Socks5 fail: {e}")
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
        await asyncio.gather(relay(reader, rw, "c->r"), relay(rr, writer, "r->c"))
    except Exception as e:
        logger.error(f"Socks5 error: {e}")
        writer.close()

async def main():
    http_server = await asyncio.start_server(http_handler, "0.0.0.0", HTTP_PORT)
    socks_server = await asyncio.start_server(socks5_handler, "0.0.0.0", SOCKS_PORT)
    logger.info(f"Config page on port {HTTP_PORT}")
    logger.info(f"SOCKS5 proxy on port {SOCKS_PORT}")
    logger.info("=" * 50)
    logger.info("VLESS Link:")
    logger.info(VLESS_LINK)
    logger.info("=" * 50)
    await asyncio.gather(http_server.serve_forever(), socks_server.serve_forever())

if __name__ == "__main__":
    asyncio.run(main())
