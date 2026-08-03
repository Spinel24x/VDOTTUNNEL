"""
VDOT connection test.
Starts a temporary SOCKS5 proxy, connects to VDOT server, fetches a test URL.
"""
import asyncio
import sys
import os
import subprocess
import time
import requests
from vdot_client import Socks5Server, VDOT_SERVER_URI, VDOT_UUID, SOCKS_PORT

async def test_connection():
    print(f"Testing VDOT connection to {VDOT_SERVER_URI} with UUID {VDOT_UUID}")
    # Start a SOCKS5 server in the background
    socks = Socks5Server(port=SOCKS_PORT)
    task = asyncio.create_task(socks.start())
    await asyncio.sleep(1)  # wait for server start
    # Use a simple test request
    try:
        # Wait a bit for the server to be ready
        proxies = {'http': f'socks5://127.0.0.1:{SOCKS_PORT}',
                   'https': f'socks5://127.0.0.1:{SOCKS_PORT}'}
        resp = requests.get('http://checkip.amazonaws.com', proxies=proxies, timeout=10)
        if resp.status_code == 200:
            print(f"✅ Connection successful! Your external IP: {resp.text.strip()}")
        else:
            print(f"❌ Test failed with status {resp.status_code}")
    except Exception as e:
        print(f"❌ Test error: {e}")
    finally:
        task.cancel()
        sys.exit(0)

if __name__ == "__main__":
    asyncio.run(test_connection())
