# Release engineering notes: v0.1.0

Working log for the steps between "works on my machine" and `pip install nengok` succeeding for a stranger. The polished changelog lives in [CHANGELOG.md](../CHANGELOG.md); this file records what was checked, what broke, and how it was fixed, so the next release does not rediscover the same problems.

## PyPI name claim

Checked on 2026-06-10: `https://pypi.org/pypi/nengok/json` returns 404, so the name is unclaimed and every badge and install instruction in the repo can keep saying `nengok`. The fallback `nengok-sdk` is also free, so no rename is needed.

PyPI has no reservation step short of an upload; the name is claimed by the first successful publish. To make that publish work without an API token:

1. On pypi.org, add a pending trusted publisher for project `nengok` pointing at the `waizwafiq/Nengok` repo, workflow `publish.yml`, environment `pypi`. The tag-triggered publish job then claims the name on the first `v*.*.*` push.
2. On test.pypi.org, add the same pending publisher with environment `testpypi`. The dry-run job that fires on every `main` push exercises the full build-and-upload path there, so the first real release is not the first run of the workflow.

Both steps are dashboard actions for the repo owner; nothing else in the repo changes.
