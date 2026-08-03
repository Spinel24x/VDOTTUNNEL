#!/usr/bin/env python3
"""
VDOT Server - supports both raw VLESS over WS and VDOT (DNS-wrapped) protocols.
Deploy on Railway with auto-TLS.
"""
import asyncio
import logging
import os
import uuid
import websockets
from websockets.exceptions import ConnectionClosed
from vless import parse_request, build_response, VlessRequest
from dns_utils import (
    create_dns_query, extract_payload_from_query,
    create_dns_response, extract_payload_from_response
)
import dns.message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vdot-server")

# Configuration
UUID = os.environ.get("UUID")
if not UUID:
    UUID = str(uuid.uuid4())
    logger.info(f"Generated new UUID: {UUID}")
else:
    logger.info(f"Using UUID: {UUID}")

LISTEN_HOST = "0.0.0.0"
LISTEN_PORT = int(os.environ.get("PORT", "8080"))
WS_PATH = "/vdot"  # WebSocket endpoint path

VALID_UUID = uuid.UUID(UUID).bytes

# ----- Raw VLESS over WS handler -----
async def handle_raw_vless(websocket, initial_data: bytes):
    """Handle a direct VLESS connection (no DNS wrapping)."""
    try:
        req = parse_request(initial_data)
    except Exception as e:
        logger.warning(f"VLESS parse error: {e}")
        await websocket.close(1011, "Bad VLESS request")
        return
    if req.uuid != VALID_UUID:
        logger.info("UUID mismatch")
        await websocket.send(build_response(False))
        await websocket.close()
        return
    # Connect to destination
    try:
        if req.addr_type == 0x01:  # IPv4
            addr_str = ".".join(str(b) for b in req.addr)
        elif req.addr_type == 0x03:  # Domain
            addr_str = req.addr.decode()
        else:
            await websocket.send(build_response(False))
            return
        logger.info(f"Raw VLESS connecting to {addr_str}:{req.port}")
        reader, writer = await asyncio.open_connection(addr_str, req.port)
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        await websocket.send(build_response(False))
        return
    await websocket.send(build_response(True))
    # Bidirectional relay
    async def ws_to_target():
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    writer.write(message)
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

# ----- VDOT (DNS-wrapped) handler -----
async def handle_vdot(websocket, initial_http_request: str):
    """Handle a VDOT connection where VLESS is inside DNS inside HTTP."""
    # We'll receive full HTTP requests as text frames, but might be binary.
    # We'll handle both by encoding.
    # Parse HTTP request (very basic)
    try:
        # Split headers and body
        header_end = initial_http_request.find("\r\n\r\n")
        if header_end == -1:
            await websocket.close(1011, "Invalid HTTP request")
            return
        headers = initial_http_request[:header_end]
        body = initial_http_request[header_end+4:].encode() if isinstance(initial_http_request, str) else initial_http_request[header_end+4:]
        # Expect POST with application/dns-message
        if "POST /doh" not in headers or "application/dns-message" not in headers:
            await websocket.close(1011, "Wrong HTTP endpoint")
            return
        # Extract DNS query
        dns_query_wire = body
        payload = extract_payload_from_query(dns_query_wire)
        # Parse VLESS request from payload
        try:
            req = parse_request(payload)
        except Exception as e:
            logger.warning(f"VDOT VLESS parse error: {e}")
            # Send error
            err_payload = build_response(False)
            resp_wire = create_dns_response(dns.message.from_wire(dns_query_wire), err_payload)
            http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
            await websocket.send(http_resp)
            return
        if req.uuid != VALID_UUID:
            logger.info("VDOT UUID mismatch")
            err_payload = build_response(False)
            resp_wire = create_dns_response(dns.message.from_wire(dns_query_wire), err_payload)
            http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
            await websocket.send(http_resp)
            return
        # Connect to target
        try:
            if req.addr_type == 0x01:
                addr_str = ".".join(str(b) for b in req.addr)
            elif req.addr_type == 0x03:
                addr_str = req.addr.decode()
            else:
                raise ValueError("Invalid address type")
            logger.info(f"VDOT connecting to {addr_str}:{req.port}")
            reader, writer = await asyncio.open_connection(addr_str, req.port)
        except Exception as e:
            logger.error(f"VDOT connect failed: {e}")
            err_payload = build_response(False)
            resp_wire = create_dns_response(dns.message.from_wire(dns_query_wire), err_payload)
            http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
            await websocket.send(http_resp)
            return
        # Success response
        success_payload = build_response(True)
        resp_wire = create_dns_response(dns.message.from_wire(dns_query_wire), success_payload)
        http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
        await websocket.send(http_resp)
        # Relay loop
        async def ws_to_target():
            try:
                async for message in websocket:
                    # Each message is an HTTP request with DNS query containing data
                    if isinstance(message, str):
                        h_end = message.find("\r\n\r\n")
                        if h_end == -1:
                            continue
                        body = message[h_end+4:].encode()
                    else:
                        body = message  # might be binary HTTP
                        # But we assume text frames for HTTP
                        # For simplicity, we just take whole message as body if no headers? Not robust.
                        # We'll use the same parsing as before, but we need to re-implement.
                        # This is a simplified version; for production, use a proper HTTP parser.
                        # For now, assume each frame is a complete HTTP request.
                        h_end = body.find(b"\r\n\r\n")
                        if h_end >= 0:
                            body = body[h_end+4:]
                    dns_q = body
                    data = extract_payload_from_query(dns_q)
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
                    # Wrap data in DNS response -> HTTP response
                    # Need a dummy request to create response, we use a fixed one
                    q_msg = dns.message.make_query(DUMMY_QNAME, dns.rdatatype.A)
                    resp_wire = create_dns_response(q_msg, data)
                    http_resp = f"HTTP/1.1 200 OK\r\nContent-Type: application/dns-message\r\nContent-Length: {len(resp_wire)}\r\n\r\n".encode() + resp_wire
                    await websocket.send(http_resp)
            except ConnectionClosed:
                pass
            finally:
                await websocket.close()
        await asyncio.gather(ws_to_target(), target_to_ws())
    except Exception as e:
        logger.error(f"VDOT handler error: {e}")
        await websocket.close(1011, "Internal error")

# ----- Main dispatcher -----
async def dispatcher(websocket, path):
    if path != WS_PATH:
        await websocket.close(1008, "Invalid path")
        return
    try:
        # Wait for first message
        first_msg = await websocket.recv()
    except ConnectionClosed:
        return
    if isinstance(first_msg, str) and first_msg.startswith("POST "):
        # Likely VDOT HTTP request
        await handle_vdot(websocket, first_msg)
    elif isinstance(first_msg, bytes):
        # Raw VLESS binary
        await handle_raw_vless(websocket, first_msg)
    else:
        await websocket.close(1011, "Unknown protocol")

async def main():
    logger.info(f"VDOT server starting on {LISTEN_HOST}:{LISTEN_PORT}, path={WS_PATH}")
    async with websockets.serve(dispatcher, LISTEN_HOST, LISTEN_PORT):
        await asyncio.Future()  # run forever

if __name__ == "__main__":
    asyncio.run(main())
