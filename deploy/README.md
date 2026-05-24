# `deploy/` — hosted demo only

Nengok's normal install path is `pip install nengok` plus a local
dashboard launched via `nengok dashboard`. The contents of this
directory exist solely to satisfy the hackathon's "hosted project URL"
requirement.

- **`Dockerfile`**: multi-stage build that bakes the Vite frontend
  into `nengok/server`'s static mount and runs `nengok dashboard` on
  `0.0.0.0:8765`.
- **`cloud-run.yaml`**: Cloud Run service manifest. CI substitutes
  the built image reference at deploy time.

If you are evaluating Nengok as a user, ignore this directory.
