import asyncio
import tempfile
from pathlib import Path
from pageql.pageqlapp import PageQLApp


async def _run_upload_test(data: bytes):
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "u.pageql").write_text(
            "{%partial post upload%} {{length(:file.body)}} {%endpartial%}",
            encoding="utf-8",
        )
        app = PageQLApp(
            ":memory:", tmpdir, create_db=True, should_reload=False, csrf_protect=False
        )
        boundary = "BOUNDARY"
        body = (
            f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename=\"t.txt\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        headers = [
            (b"content-type", f"multipart/form-data; boundary={boundary}".encode()),
            (b"content-length", str(len(body)).encode()),
        ]
        sent = []

        async def send(msg):
            sent.append(msg)

        parts = [body[: len(body) // 2], body[len(body) // 2 :]]
        it = iter(parts)

        async def receive():
            try:
                part = next(it)
            except StopIteration:
                return {"type": "http.disconnect"}
            return {
                "type": "http.request",
                "body": part,
                "more_body": part is not parts[-1],
            }

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/u/upload",
            "headers": headers,
            "query_string": b"",
        }
        await app.pageql_handler(scope, receive, send)
        body_msg = next(m for m in sent if m["type"] == "http.response.body")
        return body_msg["body"].decode().strip()


def test_large_file_upload_reads_all_bytes():
    result = asyncio.run(_run_upload_test(b"A" * 10240))
    assert "10240" in result

