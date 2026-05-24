## Summary

<!-- 1-3 bullets: what changed and why. -->

## Scope

- [ ] SDK / engine (`nengok/`)
- [ ] Dashboard frontend (`frontend/`)
- [ ] Sample agent (`sample_agent/`)
- [ ] Phoenix integration harness (`phoenix_harness/`)
- [ ] Golden dataset (`golden_dataset/`)
- [ ] Deployment / infra (`deploy/`)
- [ ] CI/CD (`.github/`)
- [ ] Documentation

## Test plan

- [ ] `ruff check nengok tests` passes (if SDK touched)
- [ ] `ruff format --check nengok tests` passes (if SDK touched)
- [ ] `pytest tests/` passes (if SDK touched)
- [ ] `cd frontend && npm run lint && npm run build` passes (if FE touched)
- [ ] Ran `nengok run` end-to-end against a local Phoenix instance (if loop logic touched)
- [ ] Phoenix harness still green (`pytest phoenix_harness/`)
- [ ] No regression on the golden dataset (if evaluators / prompts touched)

## Human-in-the-loop check

- [ ] No code path auto-applies a fix without human approval
- [ ] No trace data is sent to a third-party endpoint
- [ ] Artifacts are written to the local `artifacts/` directory only

## Screenshots / GIFs (dashboard changes only)

<!-- Paste before/after or a quick screen recording. -->
