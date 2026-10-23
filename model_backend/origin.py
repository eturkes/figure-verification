# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Request origin for the loopback OpenAI servers: the model backend, the stub, the codex bridge.

None authenticates its caller, so each answers only the `Host` headers `hosts` derives from its
bind (a DNS-rebound page names its own domain, so it reads no reply) and only a JSON body
(`json_only`: a page in the operator's browser can post `text/plain` to loopback with no CORS
preflight; Open WebUI 0.12.3 + nucllei send JSON). M23.1 F2 (bridge) + F4 (backend, stub).
"""

from typing import Any

from litestar import Request, Response


def hosts(hostname: str, port: int) -> tuple[str, ...]:
    """The `Host` headers a server bound to hostname:port answers: its bind name + the loopback
    spellings, each with the port (Litestar's `allowed_hosts` matches the whole header)."""
    named = f"[{hostname}]" if ":" in hostname else hostname
    spellings = dict.fromkeys((named, "127.0.0.1", "localhost", "[::1]"))
    return tuple(f"{name}:{port}" for name in spellings)


def json_only(request: Request[Any, Any, Any]) -> Response[dict[str, object]] | None:
    """`before_request` hook of a POST route: a body that is not `application/json` = 415, before
    Litestar reads or decodes it."""
    if request.content_type[0] == "application/json":
        return None
    error = {"message": "the body must be application/json", "type": "invalid_request_error"}
    return Response({"error": error}, status_code=415)
