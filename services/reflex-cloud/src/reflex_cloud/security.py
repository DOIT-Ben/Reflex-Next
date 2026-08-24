from __future__ import annotations

import hashlib
import hmac
from ipaddress import ip_address, ip_network
import re
import secrets

from fastapi import Request


_REDACTION_PATTERNS = (
    re.compile(
        r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----[\s\S]*?"
        r"-----END (?:[A-Z0-9 ]+ )?PRIVATE KEY-----"
    ),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}"),
    re.compile(
        r"(?i)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|secret|password)"
        r"\s*[:=]\s*[^\s,;]{8,}"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,255}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"),
    re.compile(
        r"https://hooks\.slack\.com/services/"
        r"[A-Za-z0-9_-]{6,}/[A-Za-z0-9_-]{6,}/[A-Za-z0-9_-]{16,}"
    ),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{16,}\b"),
    re.compile(r"\bAIza[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\b(?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,}\b"),
)


def new_installation_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str, pepper: str) -> str:
    return hmac.new(pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def redact_text(value: str) -> str:
    redacted = value
    for pattern in _REDACTION_PATTERNS:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def secure_equals(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def resolve_client_ip(request: Request, trusted_proxy_cidrs: str) -> str | None:
    peer = _parse_ip(request.client.host if request.client else "")
    if peer is None:
        return None
    trusted = tuple(
        ip_network(item) for item in trusted_proxy_cidrs.split(",") if item
    )
    if not any(peer in network for network in trusted):
        return str(peer)

    forwarded = _forwarded_chain(request)
    if not forwarded:
        return str(peer)
    for address in reversed((*forwarded, peer)):
        if not any(address in network for network in trusted):
            return str(address)
    return str(forwarded[0])


def _forwarded_chain(request: Request):
    raw = request.headers.get("x-forwarded-for", "")
    if raw:
        values = [item.strip() for item in raw.split(",")]
    else:
        values = []
        for element in request.headers.get("forwarded", "").split(","):
            for parameter in element.split(";"):
                name, separator, value = parameter.strip().partition("=")
                if separator and name.lower() == "for":
                    values.append(value.strip().strip('"'))
                    break
    addresses = []
    for value in values:
        address = _parse_ip(value)
        if address is None:
            return ()
        addresses.append(address)
    return tuple(addresses)


def _parse_ip(value: str):
    candidate = value.strip().strip('"')
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    elif candidate.count(":") == 1 and "." in candidate:
        candidate = candidate.rsplit(":", 1)[0]
    try:
        return ip_address(candidate)
    except ValueError:
        return None
