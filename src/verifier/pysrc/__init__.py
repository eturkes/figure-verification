# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Portable verification core for `pysrc-0.1` (model-authored Python).

Stdlib-only and importing no `verifier` sibling on purpose: M14 inlines this package into a
single file an admin pastes into an Open WebUI instance that has no outside network access, so a
dependency here becomes a dependency there. Where reuse of the shipped service code conflicts with
that isolation, isolation wins (`.claude/rules/pysrc.md`).

`verify_python_source` is the ONLY entry a consumer calls; everything else exported here is a
value it returns or a policy it accepts. The stage functions stay reachable by module path for
ordering tests, but they are not part of this surface.
"""

from verifier.pysrc.certificate import (
    CertifiedCheck as CertifiedCheck,
)
from verifier.pysrc.certificate import (
    CoreCertificate as CoreCertificate,
)
from verifier.pysrc.errors import (
    PysrcCallerError as PysrcCallerError,
)
from verifier.pysrc.errors import (
    PysrcRefusalError as PysrcRefusalError,
)
from verifier.pysrc.errors import (
    RefusalCode as RefusalCode,
)
from verifier.pysrc.limits import DEFAULT_LIMITS as DEFAULT_LIMITS
from verifier.pysrc.limits import PysrcLimits as PysrcLimits
from verifier.pysrc.spec import DatasetTarget as DatasetTarget
from verifier.pysrc.spec import DeclaredTarget as DeclaredTarget
from verifier.pysrc.spec import FormulaTarget as FormulaTarget
from verifier.pysrc.table import CellValue as CellValue
from verifier.pysrc.table import PlottedTable as PlottedTable
from verifier.pysrc.verify import Refused, Verdict, Verified, verify_python_source

__all__ = ["Refused", "Verdict", "Verified", "verify_python_source"]
