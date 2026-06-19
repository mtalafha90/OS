from __future__ import annotations

import subprocess
import socket
from typing import Any

from .registry import tool


@tool(
    name="ping_host",
    description="Ping a hostname or IP address to check connectivity.",
    properties={
        "host": {"type": "string", "description": "Hostname or IP to ping"},
        "count": {"type": "integer", "description": "Number of packets to send (default: 4)"},
    },
    required=["host"],
)
def ping_host(host: str, count: int = 4) -> str:
    try:
        result = subprocess.run(
            ["ping", "-c", str(min(count, 10)), host],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout.strip() or result.stderr.strip()
    except FileNotFoundError:
        return "Error: 'ping' not found"
    except subprocess.TimeoutExpired:
        return f"Error: ping to {host} timed out"


@tool(
    name="check_port",
    description="Check if a TCP port is open on a host.",
    properties={
        "host": {"type": "string", "description": "Hostname or IP"},
        "port": {"type": "integer", "description": "TCP port number"},
        "timeout": {"type": "number", "description": "Connection timeout in seconds (default: 5)"},
    },
    required=["host", "port"],
)
def check_port(host: str, port: int, timeout: float = 5.0) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return f"Port {port} on {host} is OPEN"
    except (socket.timeout, ConnectionRefusedError):
        return f"Port {port} on {host} is CLOSED or unreachable"
    except OSError as e:
        return f"Error: {e}"


@tool(
    name="dns_lookup",
    description="Perform a DNS lookup for a hostname or IP address.",
    properties={
        "hostname": {"type": "string", "description": "Hostname or IP to look up"},
        "record_type": {"type": "string", "description": "DNS record type: A, AAAA, MX, NS, TXT (default: A)"},
    },
    required=["hostname"],
)
def dns_lookup(hostname: str, record_type: str = "A") -> str:
    try:
        result = subprocess.run(
            ["dig", "+short", record_type, hostname],
            capture_output=True, text=True, timeout=15
        )
        out = result.stdout.strip()
        return out if out else f"No {record_type} records found for {hostname}"
    except FileNotFoundError:
        try:
            addrs = socket.getaddrinfo(hostname, None)
            ips = sorted({a[4][0] for a in addrs})
            return "\n".join(ips)
        except socket.gaierror as e:
            return f"DNS lookup failed: {e}"


@tool(
    name="get_network_interfaces",
    description="List all network interfaces with their IP addresses and status.",
    properties={},
    required=[],
)
def get_network_interfaces() -> str:
    try:
        import psutil
        lines = []
        for iface, addrs in psutil.net_if_addrs().items():
            stats = psutil.net_if_stats().get(iface)
            status = "UP" if stats and stats.isup else "DOWN"
            lines.append(f"{iface} [{status}]")
            for addr in addrs:
                import psutil
                fam = {2: "IPv4", 10: "IPv6", 17: "MAC"}.get(addr.family, str(addr.family))
                lines.append(f"  {fam}: {addr.address}")
        return "\n".join(lines) if lines else "No interfaces found"
    except ImportError:
        result = subprocess.run(["ip", "addr"], capture_output=True, text=True, timeout=10)
        return result.stdout.strip() or result.stderr.strip()


@tool(
    name="http_request",
    description="Make an HTTP request and return the response.",
    properties={
        "url": {"type": "string", "description": "URL to request"},
        "method": {"type": "string", "description": "HTTP method: GET, POST, PUT, DELETE (default: GET)"},
        "headers": {"type": "object", "description": "Request headers as key-value pairs"},
        "body": {"type": "string", "description": "Request body (for POST/PUT)"},
        "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
    },
    required=["url"],
)
def http_request(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    body: str | None = None,
    timeout: int = 30,
) -> str:
    try:
        import httpx
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.request(method.upper(), url, headers=headers or {}, content=body)
            content = resp.text[:2000]
            return (
                f"Status: {resp.status_code}\n"
                f"Headers: {dict(resp.headers)}\n\n"
                f"Body (first 2000 chars):\n{content}"
            )
    except ImportError:
        cmd = ["curl", "-s", "-i", "-X", method.upper(), "-m", str(timeout)]
        if headers:
            for k, v in headers.items():
                cmd += ["-H", f"{k}: {v}"]
        if body:
            cmd += ["-d", body]
        cmd.append(url)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        return result.stdout[:3000] or result.stderr
    except Exception as e:
        return f"Error: {e}"


@tool(
    name="get_network_stats",
    description="Show network traffic statistics (bytes sent/received per interface).",
    properties={},
    required=[],
)
def get_network_stats() -> str:
    try:
        import psutil
        counters = psutil.net_io_counters(pernic=True)
        lines = [f"{'Interface':<15} {'Sent':>12} {'Received':>12} {'Pkt Sent':>10} {'Pkt Recv':>10}"]
        lines.append("-" * 65)
        for iface, c in counters.items():
            def fmt(n: int) -> str:
                for u in ("B","K","M","G"):
                    if n < 1024: return f"{n:.0f}{u}"
                    n //= 1024
                return f"{n}T"
            lines.append(
                f"{iface:<15} {fmt(c.bytes_sent):>12} {fmt(c.bytes_recv):>12} "
                f"{c.packets_sent:>10} {c.packets_recv:>10}"
            )
        return "\n".join(lines)
    except ImportError:
        result = subprocess.run(["cat", "/proc/net/dev"], capture_output=True, text=True)
        return result.stdout.strip()
