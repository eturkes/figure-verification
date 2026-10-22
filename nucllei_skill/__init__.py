# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""Figure verification as a nucllei skill (llens, Q82): a skill-loaded tool plus its skill text.

Every module here is written for TWO environments at once. In this repo it is ordinary first-party
code the gate lints, types and tests; on the nucllei server it arrives inside one generated tool
file (`tools/generate_paste_in.py`), with `verifier` and the shared `webui.paste_in` reply parts
embedded verbatim. `host.py` alone reaches nucllei itself, lazily, so the rest loads anywhere.

Dependency envelope: the stdlib, plus what the nucllei image already carries: `nucllei`,
`pydantic`.
"""
