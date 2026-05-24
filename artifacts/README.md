# `artifacts/` — Nengok fix output directory

Every Verifier-passed fix lands here. One subdirectory per cluster:

```
artifacts/
└── <cluster_id>/
    ├── prompt.md       # The proposed prompt body
    ├── regression.json # The generated regression dataset
    └── rca.md          # Auto-written root-cause analysis
```

The dashboard reads this directory directly. Nothing else (Git, the
cloud, a remote API) ever sees these files unless you ship them
yourself.

> Future work. When Git MCP integration lands in v0.2, an approved
> artifact bundle will be auto-committed to a branch and opened as a
> pull request. For now the artifacts stay local and a human applies
> them.
