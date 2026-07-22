# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Provisioning convergence + smoke over the WebUIClient (M4.4c).

run_bootstrap = wait_ready -> authenticate -> converge owned global filter -> attach verifier to
workspace model -> smoke: the whole hardware-free provisioning act. The admin user, filter, and
workspace model config are DB-persisted; every rerun updates the filter to this repo's exact source,
proves it active/global, and idempotently converges the model's ``meta.toolIds``. The tool server +
served model ride the launcher env, and the signin fallback makes reruns idempotent (memory M4
provisioning contract). smoke reads back the three facts that prove provisioning took:

- model_enumerated: the configured model id appears in GET /api/models (OPENAI_API_BASE_URL wired +
  ENABLE_OPENAI_API on);
- tool_registered: "server:<tool_server_id>" appears in GET /api/v1/tools/ (TOOL_SERVER_CONNECTIONS
  registered AND OWUI fetched its OpenAPI -- a server whose spec fetch fails is dropped from that
  readback, so presence proves the whole round trip);
- model_tool_attached: that server id appears in the workspace model's ``meta.toolIds``, so the
  browser frontend auto-offers the verifier without a manual tool toggle.

SmokeResult.ok = all three held. smoke/run_bootstrap take the client as a structural _Provisioner
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
    def ensure_model_tool(self, *, model_id: str, tool_id: str) -> None: ...
    def model_ids(self) -> list[str]: ...
    def tool_server_ids(self) -> list[str]: ...
    def model_tool_ids(self, model_id: str) -> list[str]: ...


class SmokeResult(msgspec.Struct, frozen=True, kw_only=True):
    """Provisioning readback ids plus the three derived presence flags; ok = all three held."""

    model_ids: tuple[str, ...]
    tool_server_ids: tuple[str, ...]
    model_tool_ids: tuple[str, ...]
    model_enumerated: bool
    tool_registered: bool
    model_tool_attached: bool

    @property
    def ok(self) -> bool:
        """Model enumerated AND the verifier tool server registered AND attached to the model."""
        return self.model_enumerated and self.tool_registered and self.model_tool_attached


def smoke(client: _Provisioner, settings: Settings) -> SmokeResult:
    """Read models + tool servers + the model's attached tools; derive the three presence flags."""
    tool_group_id = f"{_TOOL_SERVER_ID_PREFIX}{settings.tool_server_id}"
    model_ids = client.model_ids()
    tool_server_ids = client.tool_server_ids()
    model_tool_ids = client.model_tool_ids(settings.model_id)
    return SmokeResult(
        model_ids=tuple(model_ids),
        tool_server_ids=tuple(tool_server_ids),
        model_tool_ids=tuple(model_tool_ids),
        model_enumerated=settings.model_id in model_ids,
        tool_registered=tool_group_id in tool_server_ids,
        model_tool_attached=tool_group_id in model_tool_ids,
    )


def run_bootstrap(client: _Provisioner, settings: Settings) -> SmokeResult:
    """Wait, authenticate, converge the filter + model tool, then smoke all readbacks."""
    client.wait_ready()
    client.authenticate()
    client.ensure_global_filter(
        function_id=FILTER_ID,
        name=FILTER_NAME,
        content=function_source(),
        description=FILTER_DESCRIPTION,
    )
    client.ensure_model_tool(
        model_id=settings.model_id,
        tool_id=f"{_TOOL_SERVER_ID_PREFIX}{settings.tool_server_id}",
    )
    return smoke(client, settings)
