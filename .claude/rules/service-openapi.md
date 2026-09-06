---
paths:
  - "src/verifier/service/**"
  - "schema/openapi.json"
---

# Litestar service + OpenAPI

- Service: **Litestar** + **uvicorn** single-worker, 127.0.0.1 default (no loopback enforcement). Chosen over FastAPI for msgspec-native structs + OpenAPI — ergonomics, NOT a security property. Fail-closed invariant: POST bodies reach the decoder as RAW BYTES via `await request.body()` ONLY (`data: bytes` is framework-PARSED — JSON-decoded first, duplicate keys silently collapsed). CPU-bound work → async handler + `litestar.concurrency.sync_to_thread`. `@post` defaults 201 ⇒ set `status_code=200`. Body cap = `request_max_body_size`, 413 firing at the `request.body()` read (handler entered, content-type guard already run, NOT pre-dispatch); 2.24's `create_test_client` rejects the kwarg ⇒ build the app + wrap `TestClient(app=…)`. Content-type guard = `request.content_type[0] == "application/json"` else 415.
- Error split: verification outcomes INCLUDING decode failure (an expected model failure mode bench meters) = 200 verdict envelope; ONLY transport misuse / server config = RFC 9457 `application/problem+json`. Two `exception_handlers`: `HTTPException → problem+json`; `Exception → generic 500, cause LOGGED then WITHHELD`. Litestar does NOT log an exception a custom handler catches ⇒ the handler calls `_LOGGER.error(..., exc_info=exc)` itself; testing that log needs a handler on the NAMED logger AFTER app startup (startup logging config swaps root's handlers ⇒ caplog misses it).
- OpenAPI: Litestar auto-generation stays OFF (`openapi_config=None`) — it introspects response models via msgspec, whose response-encode-only `Literal[True]` arm breaks the document ⇒ hand-authored. `openapi_document()` rebases `$defs`, imports msgspec schemas + derives verdict strings; golden bytes + real-payload jsonschema tests pin it. Response unions use `anyOf` (a `RenderVerdict` also satisfies `Verdict`). `Response(content=bytes, media_type=…)` preserves canonical artifact bytes.
