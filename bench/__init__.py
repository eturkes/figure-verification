# SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
"""bench -- failure-oriented eval harness for the local model proposer (M3.4).

An out-of-tree observer of the verifier service: it drives only the public HTTP surface
(/propose-spec and /verify-only) with a synchronous httpx client and never imports verifier
internals, so it adds no trust of its own. The report separates two measurements that must never
be conflated:

  GUARANTEE (deterministic, the only bounds) -- the trusted verifier blocks all 18 M1 bad
  goldens (bad_corpus_false_accept_count == 0) AND accepts all 10 good ones
  (good_corpus_false_reject_count == 0). Either non-zero is a real regression.

  OBSERVATIONS (statistical) -- rates that characterize the weak NPU proposer (tool-call,
  json-validity, schema/semantic/policy failure, verified-render) plus its top failing checks.
  These do NOT bound the verifier; a weak model failing most prompts is the expected outcome.

Repo-root and coverage-excluded (not under src/ or tests/; coverage source is ["verifier"]): a
runnable harness, not a test, and not part of the shipped wheel. See bench/README.md for the run
recipe and the guarantee-versus-observations split.
"""
