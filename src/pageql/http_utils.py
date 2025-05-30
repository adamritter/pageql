"""Utility helpers for async HTTP interactions."""

import asyncio
import re
from urllib.parse import urlparse
from typing import Dict, List, Tuple

__all__ = ["_http_get", "_parse_multipart_data", "_read_chunked_body"]


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    """Read a HTTP chunked body from ``reader``."""
    chunks: List[bytes] = []
    while True:
        size_line = await reader.readline()
        size = int(size_line.strip(), 16)
        if size == 0:
            await reader.readline()
            break
        chunk = await reader.readexactly(size)
        chunks.append(chunk)
        await reader.readline()
    return b"".join(chunks)


def _parse_multipart_data(body: bytes, boundary: str) -> Dict[str, object]:
    """Parse ``multipart/form-data`` payloads.

    Returns a mapping of field names to either string values or
    ``{"filename": str, "body": bytes}`` for file uploads.
    """
    result: Dict[str, object] = {}
    if not boundary:
        return result
    delim = b"--" + boundary.encode()
    parts = body.split(delim)
    for part in parts[1:]:
        part = part.strip()
        if not part or part == b"--":
            continue
        if part.startswith(b"\r\n"):
            part = part[2:]
        if part.endswith(b"\r\n"):
            part = part[:-2]
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        header_bytes = part[:header_end].decode("utf-8", "ignore")
        content = part[header_end + 4 :]
        headers = {}
        for line in header_bytes.split("\r\n"):
            if ":" not in line:
                continue
            k, v = line.split(":", 1)
            headers[k.strip().lower()] = v.strip()
        disp = headers.get("content-disposition", "")
        m = re.findall(r"([a-zA-Z0-9_-]+)=\"([^\"]*)\"", disp)
        disp_dict = {k: v for k, v in m}
        name = disp_dict.get("name")
        filename = disp_dict.get("filename")
        if not name:
            continue
        if filename is not None:
            result[name] = {"filename": filename, "body": content}
        else:
            result[name] = content.decode("utf-8")
    return result


async def _http_get(url: str) -> Tuple[int, List[Tuple[bytes, bytes]], bytes]:
    """Perform a minimal async HTTP GET request."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    reader, writer = await asyncio.open_connection(
        host, port, ssl=parsed.scheme == "https"
    )
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Connection: close\r\n"
        "\r\n"
    )
    writer.write(request.encode())
    await writer.drain()

    status_line = await reader.readline()
    parts = status_line.decode().split()
    status = int(parts[1]) if len(parts) > 1 else 502
    headers: List[Tuple[bytes, bytes]] = []
    hdr_dict = {}
    while True:
        line = await reader.readline()
        if line == b"\r\n":
            break
        key, val = line.decode().split(":", 1)
        val = val.strip()
        headers.append((key.lower().encode(), val.encode()))
        hdr_dict[key.lower()] = val

    if hdr_dict.get("transfer-encoding") == "chunked":
        body = await _read_chunked_body(reader)
    elif "content-length" in hdr_dict:
        length = int(hdr_dict["content-length"])
        body = await reader.readexactly(length)
    else:
        body = await reader.read()

    writer.close()
    await writer.wait_closed()
    return status, headers, body
