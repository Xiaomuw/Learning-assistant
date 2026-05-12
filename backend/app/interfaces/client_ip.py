from __future__ import annotations

import ipaddress
import os
from collections.abc import Mapping
from typing import Any

IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address
IPNetwork = ipaddress.IPv4Network | ipaddress.IPv6Network


def client_host_from_request(request: Any) -> str | None:
    """Resolve the rate-limit client host from a FastAPI/Starlette request."""

    client = getattr(request, "client", None)
    peer_host = getattr(client, "host", None)
    headers = getattr(request, "headers", {}) or {}
    return resolve_client_host(peer_host=peer_host, headers=headers)


def resolve_client_host(*, peer_host: str | None, headers: Mapping[str, str]) -> str | None:
    peer_ip = _parse_ip(peer_host)
    if peer_ip is None:
        return _clean_host(peer_host)
    if not _is_trusted_proxy(peer_ip):
        return str(peer_ip)

    forwarded_for = _get_header(headers, "x-forwarded-for")
    for raw_item in str(forwarded_for or "").split(","):
        forwarded_ip = _parse_ip(raw_item)
        if forwarded_ip is not None:
            return str(forwarded_ip)

    real_ip = _parse_ip(_get_header(headers, "x-real-ip"))
    return str(real_ip or peer_ip)


def _is_trusted_proxy(peer_ip: IPAddress) -> bool:
    return any(peer_ip in network for network in _trusted_proxy_networks())


def _trusted_proxy_networks() -> list[IPNetwork]:
    networks: list[IPNetwork] = []
    raw = os.getenv("AUTH_TRUSTED_PROXY_IPS", "")
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            networks.append(ipaddress.ip_network(value, strict=False))
        except ValueError:
            continue
    return networks


def _parse_ip(value: str | None) -> IPAddress | None:
    candidate = _clean_host(value)
    if not candidate:
        return None
    if candidate.startswith("[") and "]" in candidate:
        candidate = candidate[1 : candidate.index("]")]
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        pass
    if candidate.count(":") == 1 and "." in candidate:
        host, _port = candidate.rsplit(":", 1)
        try:
            return ipaddress.ip_address(host)
        except ValueError:
            return None
    return None


def _clean_host(value: str | None) -> str | None:
    candidate = str(value or "").strip().strip('"').strip("'")
    return candidate or None


def _get_header(headers: Mapping[str, str], name: str) -> str:
    if hasattr(headers, "get"):
        value = headers.get(name)
        if value is not None:
            return str(value)
        value = headers.get(name.lower())
        if value is not None:
            return str(value)
        value = headers.get(name.upper())
        if value is not None:
            return str(value)
    lowered_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered_name:
            return str(value)
    return ""
