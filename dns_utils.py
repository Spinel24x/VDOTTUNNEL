"""
DNS message wrapping for VDOT.
Payload is stored in a custom EDNS option (code 65500).
"""
import dns.message
import dns.rdatatype
import dns.rdataclass
import dns.rdtypes.ANY.OPT
import dns.rdtypes.IN.A
import struct

EDNS_OPTION_CODE = 65500
DUMMY_QNAME = "vdot.tunnel."  # dummy query name
DUMMY_RESPONSE_IP = "127.0.0.1"

def create_dns_query(payload: bytes) -> bytes:
    """Create a DNS query message containing payload in EDNS."""
    q = dns.message.make_query(DUMMY_QNAME, dns.rdatatype.A)
    opt = dns.rdtypes.ANY.OPT.OPT(4096, 0, 0, [(EDNS_OPTION_CODE, payload)])
    q.use_edns(edns=True, ednsflags=0, options=opt.options)
    return q.to_wire()

def extract_payload_from_query(wire: bytes) -> bytes:
    """Extract VDOT payload from DNS query wire."""
    msg = dns.message.from_wire(wire)
    for opt in msg.options:
        if opt.otype == EDNS_OPTION_CODE:
            return opt.data
    raise ValueError("No VDOT payload found in DNS query")

def create_dns_response(request_msg: dns.message.Message, payload: bytes) -> bytes:
    """Build a DNS response to the given request, with payload in EDNS."""
    resp = dns.message.make_response(request_msg)
    resp.set_rcode(dns.rcode.NOERROR)
    # Add a dummy A record to make it look normal
    rrset = resp.find_rrset(resp.answer, dns.name.from_text(DUMMY_QNAME),
                            dns.rdataclass.IN, dns.rdatatype.A, create=True)
    rrset.add(dns.rdtypes.IN.A.A(dns.rdataclass.IN, dns.rdatatype.A, DUMMY_RESPONSE_IP))
    opt = dns.rdtypes.ANY.OPT.OPT(4096, 0, 0, [(EDNS_OPTION_CODE, payload)])
    resp.use_edns(edns=True, ednsflags=0, options=opt.options)
    return resp.to_wire()

def extract_payload_from_response(wire: bytes) -> bytes:
    """Extract VDOT payload from DNS response wire."""
    msg = dns.message.from_wire(wire)
    for opt in msg.options:
        if opt.otype == EDNS_OPTION_CODE:
            return opt.data
    raise ValueError("No VDOT payload found in DNS response")
