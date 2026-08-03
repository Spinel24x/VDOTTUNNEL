#!/usr/bin/env python3
"""
VDOT Server - supports raw VLESS over WS, VDOT (DNS-wrapped), and serves config page.
"""
import asyncio
import logging
import os
import uuid
import json
import websockets
from websockets.exceptions import ConnectionClosed
from http import HTTPStatus
from vless import parse_request, build_response
from dns_utils import (
    create_dns_query, extract_payload_from_query,
    create_dns_response, extract_payload_from_response
)
import dns.message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vdot-server")

UUID = os.environ.get("UUID")
if not UUID:
    UUID = str(uuid.uuid4())
    logger.info(f"Generated new UUID: {UUID}")
else:
    logger.info(f"Using UUID: {UUID}")

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
WS_PATH = "/vdot"
VALID_UUID = uuid.UUID(UUID).bytes

# Railway public domain (for config generation)
PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:8080")

# ... (بقیه توابع handle_raw_vless و handle_vdot بدون تغییر - دقیقاً مثل قبل)

async def handle_raw_vless(websocket, initial_data: bytes):
    # ... (همان کد قبلی، بدون تغییر)
    pass

async def handle_vdot(websocket, initial_http_request: str):
    # ... (همان کد قبلی، بدون تغییر)
    pass

# ----- HTTP request handler (for config page) -----
async def process_request(path, request_headers):
    """Handle HTTP requests before WebSocket upgrade."""
    if path == "/" or path == "/config":
        # Generate VLESS config link
        vless_link = f"vless://{UUID}@{PUBLIC_DOMAIN}:443?path=%2Fvdot&security=tls&type=ws&host={PUBLIC_DOMAIN}#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
        # Simple HTML page
        html = f"""<!DOCTYPE html>
<html>
<head><title>VDOT Config</title><meta charset="utf-8"></head>
<body style="font-family: sans-serif; max-width: 600px; margin: 50px auto;">
    <h1>🚀 VDOT Tunnel Config</h1>
    <p>Your tunnel is ready.</p>
    <h3>VLESS Link (for v2rayNG / V2Ray clients)</h3>
    <textarea rows="3" style="width:100%;font-family:monospace;">{vless_link}</textarea>
    <p><b>UUID:</b> {UUID}<br>
       <b>Domain:</b> {PUBLIC_DOMAIN}<br>
       <b>Path:</b> {WS_PATH}</p>
    <h3>VDOT Custom Client Config</h3>
    <pre>
export VDOT_HOST="{PUBLIC_DOMAIN}"
export VDOT_PORT="443"
export VDOT_PATH="{WS_PATH}"
export VDOT_UUID="{UUID}"
export SOCKS_PORT="1080"
    </pre>
    <p>Then run: <code>python client/vdot_client.py</code></p>
</body>
</html>"""
        # Return HTTP response
        headers = {
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*"
        }
        return HTTPStatus.OK, headers, html.encode()

    # For other paths, we can just return 404 or None to allow WebSocket handling
    return None

async def dispatcher(websocket, path):
    if path != WS_PATH:
        await websocket.close(1008, "Invalid path")
        return
    try:
        first_msg = await websocket.recv()
    except ConnectionClosed:
        return
    if isinstance(first_msg, str) and first_msg.startswith("POST "):
        await handle_vdot(websocket, first_msg)
    elif isinstance(first_msg, bytes):
        await handle_raw_vless(websocket, first_msg)
    else:
        await websocket.close(1011, "Unknown protocol")

async def main():
    logger.info(f"VDOT server starting on {LISTEN_HOST}:{LISTEN_PORT}, path={WS_PATH}")
    async with websockets.serve(
        dispatcher,
        LISTEN_HOST,
        LISTEN_PORT,
        process_request=process_request,
        ping_interval=None  # optional, keep alive
    ):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
