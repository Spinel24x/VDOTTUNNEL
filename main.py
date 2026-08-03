#!/usr/bin/env python3
"""VDOT gRPC Server – Config page only."""
import asyncio, os, logging, sys

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger("vdot-grpc")

HTTP_PORT = int(os.environ.get("HTTP_PORT", "10000"))
UUID = os.environ.get("UUID")
if not UUID:
    import uuid as _uu
    UUID = str(_uu.uuid4())
PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")

VLESS_LINK = (
    f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
    f"?type=grpc&security=tls"
    f"&serviceName=game"
    f"&host={PUBLIC_DOMAIN}"
    f"&sni={PUBLIC_DOMAIN}"
    f"&fp=randomized"
    f"#VDOT-gRPC-{PUBLIC_DOMAIN.split('.')[0]}"
)

HTML = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>VDOT gRPC</title></head>
<body style="font-family:sans-serif;max-width:600px;margin:50px auto">
<h1>🚀 VDOT gRPC Tunnel</h1>
<p>Copy the link below into <b>v2rayNG</b>:</p>
<textarea rows="3" style="width:100%;">{VLESS_LINK}</textarea>
<p><b>UUID:</b> {UUID}<br><b>Domain:</b> {PUBLIC_DOMAIN}<br><b>Service:</b> game</p>
</body></html>"""
HTML_BODY = HTML.encode()

async def http_handler(reader, writer):
    resp = f"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: {len(HTML_BODY)}\r\nConnection: close\r\n\r\n".encode() + HTML_BODY
    writer.write(resp)
    await writer.drain()
    writer.close()

async def main():
    server = await asyncio.start_server(http_handler, "0.0.0.0", HTTP_PORT)
    logger.info(f"Config page on port {HTTP_PORT}")
    logger.info("=" * 50)
    logger.info("VLESS gRPC Link:")
    logger.info(VLESS_LINK)
    logger.info("=" * 50)
    await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())
