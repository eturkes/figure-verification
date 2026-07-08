# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioning smoke over the WebUIClient (M4.3b).

run_bootstrap = wait_ready -> authenticate -> smoke: the whole hardware-free provisioning act. The
one DB-persisted write is the admin signup; the tool server + model ride the launcher env, so a
re-run over a still-running OWUI is idempotent via the signin fallback (memory M4
Provisioning-SETTLED-LIVE). smoke reads back the two facts that PROVE the launcher env took:

- model_enumerated: the configured model id appears in GET /api/models (OPENAI_API_BASE_URL wired +
  ENABLE_OPENAI_API on);
- tool_registered: "server:<tool_server_id>" appears in GET /api/v1/tools/ (TOOL_SERVER_CONNECTIONS
  registered AND OWUI fetched its OpenAPI -- a server whose spec fetch fails is dropped from that
  readback, so presence proves the whole round trip).

SmokeResult.ok = both held. smoke/run_bootstrap take the client as a structural _Provisioner
(Protocol) so a test fake drives the orchestration without any HTTP.
"""

from typing import Protocol

import msgspec

from webui.client import _TOOL_SERVER_ID_PREFIX
from webui.settings import Settings


class _Provisioner(Protocol):
    """The WebUIClient surface smoke/run_bootstrap use (structural, so a test fake satisfies it)."""

    def wait_ready(self) -> None: ...
    def authenticate(self) -> str: ...
    def model_ids(self) -> list[str]: ...
    def tool_server_ids(self) -> list[str]: ...


class SmokeResult(msgspec.Struct, frozen=True, kw_only=True):
    """The provisioning readback: enumerated model ids + registered tool-server ids, and the two
    derived booleans. ok = both held."""

    model_ids: tuple[str, ...]
    tool_server_ids: tuple[str, ...]
    model_enumerated: bool
    tool_registered: bool

    @property
    def ok(self) -> bool:
        """The configured model is enumerated AND the verifier tool server is registered."""
        return self.model_enumerated and self.tool_registered


def smoke(client: _Provisioner, settings: Settings) -> SmokeResult:
    """Read models + tool servers; derive whether the configured model and verifier are present."""
    model_ids = client.model_ids()
    tool_server_ids = client.tool_server_ids()
    return SmokeResult(
        model_ids=tuple(model_ids),
        tool_server_ids=tuple(tool_server_ids),
        model_enumerated=settings.model_id in model_ids,
        tool_registered=f"{_TOOL_SERVER_ID_PREFIX}{settings.tool_server_id}" in tool_server_ids,
    )


def run_bootstrap(client: _Provisioner, settings: Settings) -> SmokeResult:
    """wait_ready -> authenticate -> smoke: the full provisioning smoke, idempotent per run."""
    client.wait_ready()
    client.authenticate()
    return smoke(client, settings)
