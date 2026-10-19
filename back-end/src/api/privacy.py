"""Prevent OAuth codes, state and rejected legacy token URLs entering access logs."""

from starlette.types import ASGIApp, Receive, Scope, Send


class RedactOAuthQuery:
    """Uvicorn logs the shared scope at response start, after route query parsing."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http" or not scope.get("path", "").startswith("/auth/gmail/"):
            await self.app(scope, receive, send)
            return

        async def redacted_send(message):
            if message["type"] == "http.response.start":
                scope["query_string"] = b""
                headers = list(message.get("headers", []))
                headers = [
                    (name, value)
                    for name, value in headers
                    if name.lower() not in (b"cache-control", b"referrer-policy")
                ]
                headers.extend(
                    [(b"cache-control", b"no-store"), (b"referrer-policy", b"no-referrer")]
                )
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, redacted_send)
