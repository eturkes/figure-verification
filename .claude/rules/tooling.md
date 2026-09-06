---
paths:
  - "**/*.py"
  - "pyproject.toml"
---

# Tooling mechanics (ruff · httpx · second interpreter · vector regeneration)

- ruff `S603` fires when argv is not visibly constant: the `-c <code-var>` form needs `# noqa: S603`, an inline literal argv list does NOT (a proactive noqa trips RUF100). `ARG001` exempts leading-underscore names but NOT an unused pytest fixture param (which cannot be `_`-prefixed) ⇒ omit the fixture. `ruff format` UN-wraps a parenthesized single string fitting ≤100 cols but KEEPS a multi-segment implicit concatenation split, flipping each segment to double quotes except one holding a `"`.
- `httpx` imports directly in tests (transitive via Litestar's TestClient, lockfile-pinned). `AsyncClient(timeout=N).timeout == httpx.Timeout(N)` (one arg fans out to every component). Neither `httpx.Timeout` nor `AsyncClient(timeout=)` VALIDATES: `0` times out every request immediately (NOT disabled), negative undefined, `None` disables, non-finite passes through (`inf` hangs unbounded, `nan` raises at request time) ⇒ guard `math.isfinite(t) and t > 0`.
- Second interpreter: `UV_PROJECT_ENVIRONMENT=.scratch/venv-py3135 UV_LINK_MODE=copy COVERAGE_FILE=.scratch/coverage-py3135 uv run --locked --python 3.13.5 pytest -q -p no:cacheprovider`. VCert vectors: `PYTHONPATH=$PWD/tests uv run --locked python tests/regenerate_vcert_vectors.py` (idempotent; rewrites only the two real-pipeline entries, copies `synthetic_*` verbatim).
