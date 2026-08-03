"""
Minimal VLESS protocol implementation for VDOT.
Supports only TCP command with IPv4/domain addresses.
"""
import struct
import uuid as uuid_lib

VLESS_VERSION = 0
CMD_TCP = 0x01
ATYPE_IPV4 = 0x01
ATYPE_DOMAIN = 0x03
ATYPE_IPV6 = 0x04

RESPONSE_SUCCESS = 0x00
RESPONSE_ERROR   = 0x01

class VlessRequest:
    def __init__(self, uuid: bytes, cmd: int, port: int, addr_type: int, addr: bytes):
        self.uuid = uuid
        self.cmd = cmd
        self.port = port
        self.addr_type = addr_type
        self.addr = addr

def parse_request(data: bytes) -> VlessRequest:
    """Parse a VLESS request. Returns VlessRequest on success."""
    if len(data) < 19:
        raise ValueError("VLESS packet too short")
    ver = data[0]
    if ver != VLESS_VERSION:
        raise ValueError(f"Unsupported VLESS version: {ver}")
    uid = data[1:17]
    cmd = data[17]
    if cmd != CMD_TCP:
        raise ValueError(f"Unsupported command: {cmd}")
    port = struct.unpack("!H", data[18:20])[0]
    atype = data[20]
    if atype == ATYPE_IPV4:
        addr_len = 4
        addr = data[21:21+addr_len]
    elif atype == ATYPE_DOMAIN:
        addr_len = data[21]
        addr = data[22:22+addr_len]
    elif atype == ATYPE_IPV6:
        addr_len = 16
        addr = data[21:21+addr_len]
    else:
        raise ValueError(f"Unknown address type: {atype}")
    return VlessRequest(uid, cmd, port, atype, addr)

def build_response(success: bool) -> bytes:
    """Build a VLESS response (1 byte)."""
    return bytes([RESPONSE_SUCCESS if success else RESPONSE_ERROR])

def build_request(uuid: str, host: str, port: int, is_domain: bool = True) -> bytes:
    """Build a VLESS request for the given destination."""
    uid = uuid_lib.UUID(uuid).bytes
    cmd = CMD_TCP
    port_bytes = struct.pack("!H", port)
    if is_domain:
        host_bytes = host.encode()
        if len(host_bytes) > 255:
            raise ValueError("Domain name too long")
        atype = ATYPE_DOMAIN
        addr_field = bytes([len(host_bytes)]) + host_bytes
    else:
        import ipaddress
        ip = ipaddress.ip_address(host)
        if ip.version == 4:
            atype = ATYPE_IPV4
            addr_field = ip.packed
        else:
            atype = ATYPE_IPV6
            addr_field = ip.packed
    header = struct.pack("!B", VLESS_VERSION) + uid + struct.pack("!B", cmd) + port_bytes + struct.pack("!B", atype) + addr_field
    return header
