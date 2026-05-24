"""
Live integration tests against a real Phoenix instance.

The harness is intentionally separate from `tests/`:

  - `tests/` runs on every PR (CI), uses fakes, no network.
  - `phoenix_harness/` runs against a live Phoenix server gated by the
    `PHOENIX_BASE_URL` repo secret. It's the smoke test we run before
    pinning a new Phoenix client version.
"""
