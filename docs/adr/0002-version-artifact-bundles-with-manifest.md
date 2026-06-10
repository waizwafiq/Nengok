# Version artifact bundles with a manifest

Status: accepted

Artifact bundles are part of Nengok's audit surface, so every per-cluster artifact directory must include a `manifest.json` with `schema_version`, `cluster_id`, `generated_at`, declared artifact filenames, and SHA-256 hashes. The manifest is written last, after artifact files are flushed, and every artifact reader must call `assert_manifest_version(supported=[1])` before touching bundle fields. This makes schema drift detectable for dashboard, export, digest, and notifier readers, preserving long-term auditability for old bundles instead of silently misreading them.

## Considered options

- Keep the current implicit directory shape: rejected because readers would break or silently misread old bundles when fields are added or renamed.
- Add only `schema_version`: rejected because hashes are cheap once a manifest exists and provide tamper evidence for audit bundles.
- Write the manifest last: accepted because readers either see a complete manifest or no manifest, avoiding a manifest that claims files exist before they are present.

## Consequences

- Artifact manifest support is Phase 0 for notification surfaces, digest, audit export improvements, and any artifact-aware notifier.
- Readers must reject unsupported or incomplete bundles rather than best-effort parsing them.
- A bundle with no manifest is an unversioned legacy bundle and must be handled explicitly, not treated as version 1 by assumption.
