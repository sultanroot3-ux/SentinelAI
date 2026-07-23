"""Trusted-proxy-aware client IP resolution.

`X-Forwarded-For` is client-controlled and MUST NOT be trusted blindly — doing
so lets an attacker rotate the header to defeat per-IP rate limiting. We only
consult XFF when the direct peer is a configured trusted proxy, and then we use
the entry the proxy appended (the last one), which the client cannot forge.

Default configuration (no trusted proxies) ignores XFF completely and uses the
real socket peer, so spoofing is impossible out of the box.
"""
import ipaddress
import logging

from fastapi import Request

from app.core.config import settings

logger = logging.getLogger("sentinelai.net")


def _peer_is_trusted(peer: str) -> bool:
    if not settings.TRUSTED_PROXY_IPS:
        return False
    try:
        addr = ipaddress.ip_address(peer)
    except ValueError:
        return False
    for entry in settings.TRUSTED_PROXY_IPS:
        try:
            if addr in ipaddress.ip_network(entry, strict=False):
                return True
        except ValueError:
            logger.warning("Invalid entry in TRUSTED_PROXY_IPS: %r", entry)
    return False


def client_ip(request: Request) -> str:
    """Resolve the real client IP, honoring X-Forwarded-For only from trusted proxies."""
    peer = request.client.host if request.client else "unknown"
    if _peer_is_trusted(peer):
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # A trusted reverse proxy (e.g. nginx with $proxy_add_x_forwarded_for)
            # APPENDS the real peer it observed as the LAST element. Earlier
            # elements are attacker-supplied and ignored.
            return forwarded.split(",")[-1].strip()
    return peer
