#!/usr/bin/env python3
"""
VDOT Client - connects to VDOT server and exposes a local SOCKS5 proxy.
"""
import asyncio
import logging
import struct
import socket
import uuid
import sys
import websockets
from vless import build_request, parse_request, build_response
from dns_utils import (
    create_dns_query, extract_payload_from_query,
    create_dns_response, extract_payload_from_response
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vdot-client")

# --- SOCKS5 server implementation (RFC 1928) ---
class Socks5Server:
    def __init__(self, host='127.0.0.1', port=1080):
        self.host = host
        self.port = port
        self.server = None

    async def handle_client(self, reader, writer):
        try:
            # Greeting
            data = await reader.readexactly(2)
            ver, nmethods = data[0], data[1]
            if ver != 5:
                writer.close()
                return
            methods = await reader.readexactly(nmethods)
            # No auth
            writer.write(b'\x05\x00')
            await writer.drain()
            # Request
            data = await reader.readexactly(4)
            ver, cmd, rsv, atype = data
            if cmd != 1:  # CONNECT
                writer.write(b'\x05\x07\x00\x01\x00\x00\x00\x00\x00\x00')  # Command not supported
                await writer.drain()
                writer.close()
                return
            dst_addr = None
            dst_port = None
            if atype == 1:  # IPv4
                addr = await reader.readexactly(4)
                dst_addr = '.'.join(str(b) for b in addr)
            elif atype == 3:  # Domain
                length = (await reader.readexactly(1))[0]
                addr = await reader.readexactly(length)
                dst_addr = addr.decode()
            elif atype == 4:  # IPv6
                addr = await reader.readexactly(16)
                dst_addr = ':'.join(f'{addr[i]:02x}{addr[i+1]:02x}' for i in range(0,16,2))
            else:
                writer.close()
                return
            port_bytes = await reader.readexactly(2)
            dst_port = struct.unpack('!H', port_bytes)[0]
            logger.info(f"SOCKS5 connect to {dst_addr}:{dst_port}")
            # Connect to VDOT server
            try:
                vdot_ws = await websockets.connect(VDOT_SERVER_URI)
                # Build VLESS request
                vless_packet = build_request(VDOT_UUID, dst_addr, dst_port)
                # Wrap in DNS query
                dns_query = create_dns_query(vless_packet)
                # Build HTTP request
                http_request = (
                    f"POST /doh HTTP/1.1\r\n"
                    f"Host: {VDOT_HOST}\r\n"
                    f"Content-Type: application/dns-message\r\n"
                    f"Content-Length: {len(dns_query)}\r\n"
                    f"\r\n"
                ).encode() + dns_query
                await vdot_ws.send(http_request)
                # Receive response
                resp = await vdot_ws.recv()
                if isinstance(resp, str):
                    resp = resp.encode()
                # Parse HTTP response
                h_end = resp.find(b"\r\n\r\n")
                if h_end == -1:
                    raise Exception("Invalid HTTP response")
                body = resp[h_end+4:]
                dns_resp = body
                vless_resp_payload = extract_payload_from_response(dns_resp)
                if vless_resp_payload[0] != 0x00:  # failure
                    raise Exception("VLESS connection refused")
                # Success, tell SOCKS5 client
                writer.write(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
                await writer.drain()
                # Start relaying
                async def socks_to_vdot():
                    try:
                        while True:
                            data = await reader.read(4096)
                            if not data:
                                break
                            dns_q = create_dns_query(data)
                            http_req = (
                                f"POST /doh HTTP/1.1\r\n"
                                f"Host: {VDOT_HOST}\r\n"
                                f"Content-Type: application/dns-message\r\n"
                                f"Content-Length: {len(dns_q)}\r\n"
                                f"\r\n"
                            ).encode() + dns_q
                            await vdot_ws.send(http_req)
                    except Exception:
                        pass
                    finally:
                        await vdot_ws.close()
                async def vdot_to_socks():
                    try:
                        async for message in vdot_ws:
                            if isinstance(message, str):
                                body = message.encode()
                            else:
                                body = message
                            # Find HTTP body
                            h_end = body.find(b"\r\n\r\n")
                            if h_end >= 0:
                                body = body[h_end+4:]
                            data = extract_payload_from_response(body)
                            writer.write(data)
                            await writer.drain()
                    except Exception:
                        pass
                    finally:
                        writer.close()
                await asyncio.gather(socks_to_vdot(), vdot_to_socks())
            except Exception as e:
                logger.error(f"VDOT tunnel error: {e}")
                writer.write(b'\x05\x01\x00\x01\x00\x00\x00\x00\x00\x00')  # General failure
                await writer.drain()
        except Exception as e:
            logger.error(f"SOCKS5 handler error: {e}")
        finally:
            writer.close()

    async def start(self):
        self.server = await asyncio.start_server(
            self.handle_client, self.host, self.port)
        addr = self.server.sockets[0].getsockname()
        logger.info(f"SOCKS5 proxy listening on {addr[0]}:{addr[1]}")

# --- Configuration from environment ---
VDOT_HOST = os.environ.get("VDOT_HOST", "localhost")
VDOT_PORT = os.environ.get("VDOT_PORT", "443")
VDOT_PATH = os.environ.get("VDOT_PATH", "/vdot")
VDOT_UUID = os.environ.get("VDOT_UUID", "00000000-0000-0000-0000-000000000000")
VDOT_SERVER_URI = f"wss://{VDOT_HOST}:{VDOT_PORT}{VDOT_PATH}"
SOCKS_PORT = int(os.environ.get("SOCKS_PORT", "1080"))

async def main():
    socks = Socks5Server(port=SOCKS_PORT)
    await socks.start()
    await asyncio.Future()  # run forever

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        from test_vdot import test_connection
        asyncio.run(test_connection())
    else:
        asyncio.run(main())
