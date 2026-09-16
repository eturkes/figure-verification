# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioning convergence + smoke over the WebUIClient.

run_bootstrap = wait_ready -> authenticate -> converge owned global filter -> converge the pasted
tool -> attach that tool to the workspace model -> smoke: the whole hardware-free provisioning act.
The admin user, filter, tool and workspace model config are DB-persisted; every rerun updates the
filter and the tool to this repo's exact bytes and idempotently converges the model's
``meta.toolIds``. The served model rides the launcher env, and the signin fallback makes reruns
idempotent (.agent/archive/m4.md provisioning contract). smoke reads back the four facts that prove
provisioning took:

- model_enumerated: the configured model id appears in GET /api/models (OPENAI_API_BASE_URL wired +
  ENABLE_OPENAI_API on);
- tool_provisioned: the pasted tool's id appears in GET /api/v1/tools/, so the artifact loaded and
  Open WebUI generated its spec (a tool whose module fails to import is rejected at write time);
- no_tool_servers: NO ``server:``-prefixed id appears in the same readback. The JSON-spec
  ``proposeSpec`` operation reached the model through a registered tool server, so its absence is
  what makes that operation unreachable -- python mode is the demo's ONE operation;
- model_tool_attached: the pasted tool's id appears in the workspace model's ``meta.toolIds``, so
  the browser frontend offers it without a manual toggle.

SmokeResult.ok = all four held. smoke/run_bootstrap take the client as a structural _Provisioner
(Protocol) so a test fake drives the orchestration without any HTTP.
"""

from typing import Protocol

import msgspec

from webui.client import _TOOL_SERVER_ID_PREFIX
from webui.enforcement_filter import (
    FILTER_DESCRIPTION,
    FILTER_ID,
    FILTER_NAME,
    function_source,
)
from webui.paste_in.bundle import TOOL_ARTIFACT, artifact_text
from webui.settings import Settings


class _Provisioner(Protocol):
    """The WebUIClient surface smoke/run_bootstrap use (structural, so a test fake satisfies it)."""

    def wait_ready(self) -> None: ...
    def authenticate(self) -> str: ...
    def ensure_global_filter(
        self,
        *,
        function_id: str,
        name: str,
        content: str,
        description: str,
    ) -> None: ...
    def ensure_tool(
        self,
        *,
        tool_id: str,
        name: str,
        content: str,
        description: str,
    ) -> None: ...
    def ensure_model_tool(self, *, model_id: str, tool_id: str) -> None: ...
    def model_ids(self) -> list[str]: ...
    def tool_ids(self) -> list[str]: ...
    def model_tool_ids(self, model_id: str) -> list[str]: ...


class SmokeResult(msgspec.Struct, frozen=True, kw_only=True):
    """Provisioning readback ids plus the four derived flags; ok = all four held."""

    model_ids: tuple[str, ...]
    tool_ids: tuple[str, ...]
    model_tool_ids: tuple[str, ...]
    model_enumerated: bool
    tool_provisioned: bool
    no_tool_servers: bool
    model_tool_attached: bool

    @property
    def ok(self) -> bool:
        """Model enumerated AND the pasted tool provisioned, attached, and alone."""
        return (
            self.model_enumerated
            and self.tool_provisioned
            and self.no_tool_servers
            and self.model_tool_attached
        )


def smoke(client: _Provisioner, settings: Settings) -> SmokeResult:
    """Read models + workspace tools + the model's attached tools; derive the four flags."""
    model_ids = client.model_ids()
    tool_ids = client.tool_ids()
    model_tool_ids = client.model_tool_ids(settings.model_id)
    return SmokeResult(
        model_ids=tuple(model_ids),
        tool_ids=tuple(tool_ids),
        model_tool_ids=tuple(model_tool_ids),
        model_enumerated=settings.model_id in model_ids,
        tool_provisioned=settings.tool_id in tool_ids,
        no_tool_servers=not any(i.startswith(_TOOL_SERVER_ID_PREFIX) for i in tool_ids),
        model_tool_attached=settings.tool_id in model_tool_ids,
    )


def run_bootstrap(client: _Provisioner, settings: Settings) -> SmokeResult:
    """Wait, authenticate, converge the filter, tool + model attachment, then smoke every readback.

    The tool is provisioned from the COMMITTED artifact, so what the demo runs is byte-for-byte
    what an admin pastes -- the demo is the artifact's own live test rather than a second wiring.
    """
    client.wait_ready()
    client.authenticate()
    client.ensure_global_filter(
        function_id=FILTER_ID,
        name=FILTER_NAME,
        content=function_source(),
        description=FILTER_DESCRIPTION,
    )
    client.ensure_tool(
        tool_id=settings.tool_id,
        name=settings.tool_name,
        content=artifact_text(TOOL_ARTIFACT),
        description=settings.tool_description,
    )
    client.ensure_model_tool(model_id=settings.model_id, tool_id=settings.tool_id)
    return smoke(client, settings)
