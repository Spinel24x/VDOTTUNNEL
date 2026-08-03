#!/usr/bin/env python3
"""
VDOT Server – VLESS over WS, VDOT (DNS‑wrapped), and web config page.
Works with websockets >= 12.0
"""
import asyncio
import logging
import os
import uuid
import websockets
from websockets.exceptions import ConnectionClosed
from vless import parse_request, build_response
from dns_utils import (
    create_dns_query, extract_payload_from_query,
    create_dns_response, extract_payload_from_response
)
import dns.message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vdot-server")

# ---------- Config ----------
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

PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost:8080")

# ---------- VLESS over WebSocket handler ----------
async def handle_raw_vless(websocket, initial_data: bytes):
    try:
        req = parse_request(initial_data)
    except Exception as e:
        logger.warning(f"VLESS parse error: {e}")
        await websocket.close(1011, "Bad request")
        return
    if req.uuid != VALID_UUID:
        logger.info("UUID mismatch")
        await websocket.send(build_response(False))
        await websocket.close()
        return
    try:
        if req.addr_type == 0x01:
            addr_str = ".".join(str(b) for b in req.addr)
        elif req.addr_type == 0x03:
            addr_str = req.addr.decode()
        else:
            await websocket.send(build_response(False))
            return
        logger.info(f"Raw VLESS → {addr_str}:{req.port}")
        reader, writer = await asyncio.open_connection(addr_str, req.port)
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        await websocket.send(build_response(False))
        return
    await websocket.send(build_response(True))
    async def ws_to_target():
        try:
            async for msg in websocket:
                if isinstance(msg, bytes):
                    writer.write(msg)
                    await writer.drain()
        except ConnectionClosed:
            pass
        finally:
            writer.close()
    async def target_to_ws():
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break
                await websocket.send(data)
        except ConnectionClosed:
            pass
        finally:
            await websocket.close()
    await asyncio.gather(ws_to_target(), target_to_ws())

# ---------- VDOT (DNS-wrapped) handler ----------
async def handle_vdot(websocket, initial_http_request: str):
    try:
        header_end = initial_http_request.find("\r\n\r\n")
        if header_end == -1:
            await websocket.close(1011, "Bad HTTP request")
            return
        headers = initial_http_request[:header_end]
        body = initial_http_request[header_end+4:].encode() if isinstance(initial_http_request, str) else initial_http_request[header_end+4:]
        if "POST /doh" not in headers or "application/dns-message" not in headers:
            await websocket.close(1011, "Wrong HTTP endpoint")
            return
        dns_query_wire = body
        payload = extract_payload_from_query(dns_query_wire)
        try:
            req = parse_request(payload)
        except Exception as e:
            logger.warning(f"VDOT parse error: {e}")
            err = build_response(False)
            qmsg = dns.message.from_wire(dns_query_wire)
            resp_wire = create_dns_response(qmsg, err)
            http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
            await websocket.send(http_resp)
            return
        if req.uuid != VALID_UUID:
            err = build_response(False)
            qmsg = dns.message.from_wire(dns_query_wire)
            resp_wire = create_dns_response(qmsg, err)
            http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
            await websocket.send(http_resp)
            return
        try:
            if req.addr_type == 0x01:
                addr_str = ".".join(str(b) for b in req.addr)
            elif req.addr_type == 0x03:
                addr_str = req.addr.decode()
            else:
                raise ValueError("Bad addr type")
            logger.info(f"VDOT → {addr_str}:{req.port}")
            reader, writer = await asyncio.open_connection(addr_str, req.port)
        except Exception as e:
            logger.error(f"VDOT connect failed: {e}")
            err = build_response(False)
            qmsg = dns.message.from_wire(dns_query_wire)
            resp_wire = create_dns_response(qmsg, err)
            http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
            await websocket.send(http_resp)
            return
        success = build_response(True)
        qmsg = dns.message.from_wire(dns_query_wire)
        resp_wire = create_dns_response(qmsg, success)
        http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
        await websocket.send(http_resp)
        async def ws_to_target():
            try:
                async for msg in websocket:
                    if isinstance(msg, str):
                        h_end = msg.find("\r\n\r\n")
                        if h_end == -1:
                            continue
                        body_part = msg[h_end+4:].encode()
                    else:
                        body_part = msg
                    data = extract_payload_from_query(body_part)
                    if data:
                        writer.write(data)
                        await writer.drain()
            except ConnectionClosed:
                pass
            finally:
                writer.close()
        async def target_to_ws():
            try:
                while True:
                    data = await reader.read(4096)
                    if not data:
                        break
                    q = dns.message.make_query("vdot.local.", 1)
                    wrapped = create_dns_response(q, data)
                    http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(wrapped)}\r\n\r\n".encode() + wrapped
                    await websocket.send(http_resp)
            except ConnectionClosed:
                pass
            finally:
                await websocket.close()
        await asyncio.gather(ws_to_target(), target_to_ws())
    except Exception as e:
        logger.error(f"VDOT handler error: {e}")
        await websocket.close(1011, "Internal error")

# ---------- HTTP config page (FIXED – returns tuple) ----------
async def process_request(connection, request):
    logger.info(f"HTTP request: path={request.path}")
    if request.path == WS_PATH:
        return None  # Let WebSocket handshake proceed

    vless_link = (
        f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
        f"?path=%2Fvdot&security=tls&type=ws&host={PUBLIC_DOMAIN}"
        f"#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
    )

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>VDOT Config</title></head>
<body style="font-family:sans-serif;max-width:600px;margin:50px auto">
    <h1>🚀 VDOT Tunnel Config</h1>
    <p>Your personal tunnel is active.</p>
    <h3>VLESS Link (for v2rayNG / V2Ray)</h3>
    <textarea rows="3" style="width:100%;font-family:monospace;">{vless_link}</textarea>
    <p><b>UUID:</b> {UUID}<br>
       <b>Domain:</b> {PUBLIC_DOMAIN}<br>
       <b>Path:</b> {WS_PATH}</p>
    <h3>VDOT Custom Client Config</h3>
    <pre>export VDOT_HOST="{PUBLIC_DOMAIN}"
export VDOT_PORT="443"
export VDOT_PATH="{WS_PATH}"
export VDOT_UUID="{UUID}"
export SOCKS_PORT="1080"</pre>
    <p>Then run: <code>python client/vdot_client.py</code></p>
    <hr>
    <small>Powered by VDOT | No logs, pure freedom</small>
</body>
</html>"""

    headers = {
        "Content-Type": "text/html; charset=utf-8",
        "Access-Control-Allow-Origin": "*"
    }
    return (200, headers, html.encode())

# ---------- Main dispatcher ----------
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
    logger.info(f"VDOT server listening on {LISTEN_HOST}:{LISTEN_PORT}, path={WS_PATH}")
    async with websockets.serve(
        dispatcher,
        LISTEN_HOST,
        LISTEN_PORT,
        process_request=process_request,
        ping_interval=None
    ):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
