#!/usr/bin/env python3
"""
VDOT Server – Web config + SOCKS5 proxy (VDOT‑ready).
Standard VLESS handled by Xray; Xray outbound to this SOCKS5 proxy.
"""
import asyncio
import os
import struct
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vdot-py")

HTTP_PORT = int(os.environ.get("HTTP_PORT", "10000"))
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "10001"))

# Read UUID from environment (set by entrypoint.sh)
UUID = os.environ.get("UUID")
if not UUID:
    import uuid as uuid_lib
    UUID = str(uuid_lib.uuid4())

PUBLIC_DOMAIN = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "localhost")

# ---------- Simple HTTP server for config page ----------
async def http_handler(reader, writer):
    data = await reader.read(4096)
    request_line = data.split(b'\r\n')[0].decode()
    path = request_line.split(' ')[1] if len(request_line.split(' ')) > 1 else '/'
    vless_link = (
        f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
        f"?path=%2Fvless-ws&security=tls&type=ws&host={PUBLIC_DOMAIN}"
        f"&fp=chrome#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
    )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>VDOT Config</title></head>
<body style="font-family:sans-serif;max-width:600px;margin:50px auto">
    <h1>🚀 VDOT Tunnel</h1>
    <p>Your tunnel is active.</p>
    <h3>Standard VLESS (v2rayNG):</h3>
    <textarea rows="3" style="width:100%;">{vless_link}</textarea>
    <p><b>UUID:</b> {UUID}<br><b>Domain:</b> {PUBLIC_DOMAIN}<br><b>Path:</b> /vless-ws</p>
    <hr>
    <p>This proxy uses the VDOT SOCKS5 engine internally.<br>
    Future activation of full DNS wrapping requires a remote VDOT endpoint.</p>
</body></html>"""
    body = html.encode()
    resp = (
        f"HTTP/1.1 200 OK\r\n"
        f"Content-Type: text/html; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\n"
        f"Connection: close\r\n\r\n"
    ).encode() + body
    writer.write(resp)
    await writer.drain()
    writer.close()

# ---------- SOCKS5 server ----------
async def socks5_handler(reader, writer):
    try:
        # Greeting
        ver, nmethods = await reader.readexactly(2)
        if ver != 5:
            writer.close(); return
        methods = await reader.readexactly(nmethods)
        # No authentication
        writer.write(b'\x05\x00')
        await writer.drain()
        # Request
        ver, cmd, rsv, atype = await reader.readexactly(4)
        if cmd != 1:  # CONNECT only
            writer.write(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')
            await writer.drain()
            writer.close(); return
        # Destination address
        if atype == 1:  # IPv4
            addr = await reader.readexactly(4)
            dst_addr = '.'.join(map(str, addr))
        elif atype == 3:  # Domain
            length = (await reader.readexactly(1))[0]
            addr = await reader.readexactly(length)
            dst_addr = addr.decode()
        elif atype == 4:  # IPv6
            addr = await reader.readexactly(16)
            dst_addr = ':'.join(f'{addr[i]:02x}{addr[i+1]:02x}' for i in range(0, 16, 2))
        else:
            writer.close(); return
        port_bytes = await reader.readexactly(2)
        dst_port = struct.unpack('!H', port_bytes)[0]
        logger.info(f"SOCKS5 connect to {dst_addr}:{dst_port}")

        # Direct TCP connection (replace with VDOT wrapper later)
        try:
            remote_reader, remote_writer = await asyncio.open_connection(dst_addr, dst_port)
        except Exception as e:
            logger.error(f"Connection to {dst_addr}:{dst_port} failed: {e}")
            writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')
            await writer.drain()
            writer.close(); return

        # Success response
        writer.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
        await writer.drain()

        # Bidirectional relay
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
    # Start HTTP config server
    http_server = await asyncio.start_server(http_handler, "0.0.0.0", HTTP_PORT)
    # Start SOCKS5 server
    socks_server = await asyncio.start_server(socks5_handler, "0.0.0.0", SOCKS_PORT)
    logger.info(f"HTTP config server on port {HTTP_PORT}")
    logger.info(f"SOCKS5 proxy on port {SOCKS_PORT}")
    vless_link = (
        f"vless://{UUID}@{PUBLIC_DOMAIN}:443"
        f"?path=%2Fvless-ws&security=tls&type=ws&host={PUBLIC_DOMAIN}"
        f"&fp=chrome#VDOT-{PUBLIC_DOMAIN.split('.')[0]}"
    )
    logger.info(f"VLESS link: {vless_link}")
    await asyncio.gather(http_server.serve_forever(), socks_server.serve_forever())

if __name__ == "__main__":
    asyncio.run(main())
