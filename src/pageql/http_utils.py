"""Utility helpers for async HTTP interactions."""

import asyncio
import re
from urllib.parse import urlparse, parse_qs
from typing import Dict, List, Tuple, Callable, Awaitable

__all__ = [
    "_http_get",
    "fetch",
    "fetch_sync",
    "_parse_multipart_data",
    "_read_chunked_body",
    "_parse_cookies",
    "_parse_form_data",
]


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


async def _parse_form_data(
    headers: Dict[str, str],
    receive: Callable[[], Awaitable[Dict[str, object]]],
    params: Dict[str, object],
    log_func: Callable[[str], None] | None = None,
) -> None:
    """Read and parse form data from an ASGI request."""

    content_length = int(headers.get("content-length", 0))
    if content_length == 0:
        return

    content_type = headers.get("content-type", "")
    message = await receive()
    post_body = message.get("body", b"")
    while message.get("more_body"):
        message = await receive()
        post_body += message.get("body", b"")

    if "application/x-www-form-urlencoded" in content_type:
        post_body = post_body.decode("utf-8")
        post_params = parse_qs(post_body, keep_blank_values=True)
        if log_func:
            log_func(f"post_params: {post_params}")
        for key, value in post_params.items():
            params[key] = value[0] if len(value) == 1 else value
    elif "multipart/form-data" in content_type:
        m = re.search("boundary=([^;]+)", content_type)
        boundary = m.group(1).strip('"') if m else ""
        files_and_params = _parse_multipart_data(post_body, boundary)
        if log_func:
            log_func(f"multipart_params: {files_and_params}")
        for key, value in files_and_params.items():
            params[key] = value
    else:
        if log_func:
            log_func(f"Warning: Unsupported Content-Type: {content_type}")


async def _http_get(
    url: str,
    method: str = "GET",
    headers: Dict[str, str] | None = None,
    body: bytes | None = None,
) -> Tuple[int, List[Tuple[bytes, bytes]], bytes]:
    """Perform a minimal async HTTP request."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    reader, writer = await asyncio.open_connection(
        host, port, ssl=parsed.scheme == "https"
    )
    hdrs = {"Host": host, "Connection": "close"}
    if headers:
        hdrs.update(headers)
    body_bytes = body or b""
    if body_bytes and "Content-Length" not in hdrs:
        hdrs["Content-Length"] = str(len(body_bytes))
    header_lines = "".join(f"{k}: {v}\r\n" for k, v in hdrs.items())
    request = f"{method} {path} HTTP/1.1\r\n{header_lines}\r\n"
    writer.write(request.encode() + body_bytes)
    await writer.drain()

    status_line = await reader.readline()
    parts = status_line.decode().split()
    status = int(parts[1]) if len(parts) > 1 else 502
    resp_headers: List[Tuple[bytes, bytes]] = []
    hdr_dict = {}
    while True:
        line = await reader.readline()
        if line == b"\r\n":
            break
        key, val = line.decode().split(":", 1)
        val = val.strip()
        resp_headers.append((key.lower().encode(), val.encode()))
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
    return status, resp_headers, body


async def fetch(url: str, headers: Dict[str, str] | None = None) -> Dict[str, object]:
    """Return a mapping with ``status_code``, ``headers`` and decoded ``body``."""
    print(f"fetching {url}")
    status, headers, body = await _http_get(url, headers=headers)
    print(f"fetched {url} with status: {status}")
    try:
        body = body.decode("utf-8")
    except Exception:
        pass
    return {"status_code": status, "headers": headers, "body": body}


def fetch_sync(url: str, headers: Dict[str, str] | None = None) -> Dict[str, object]:
    """Synchronous variant of :func:`fetch` using ``urllib``."""
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError

    req = Request(url, headers=headers or {})
    try:
        with urlopen(req) as resp:
            status = resp.status
            headers = [(k.lower().encode(), v.encode()) for k, v in resp.getheaders()]
            body_bytes = resp.read()
    except HTTPError as e:
        status = e.code
        headers = [(k.lower().encode(), v.encode()) for k, v in e.headers.items()]
        body_bytes = e.read()
    try:
        body = body_bytes.decode("utf-8")
    except Exception:
        body = body_bytes
    return {"status_code": status, "headers": headers, "body": body}


def _parse_cookies(cookie_header: str) -> Dict[str, str]:
    """Parse an HTTP ``Cookie`` header into a mapping."""
    cookies: Dict[str, str] = {}
    if not cookie_header:
        return cookies
    for part in cookie_header.split(';'):
        if '=' not in part:
            continue
        name, value = part.split('=', 1)
        cookies[name.strip()] = value.strip()
    return cookies
