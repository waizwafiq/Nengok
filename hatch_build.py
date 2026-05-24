"""
Hatchling build hook that compiles the Vite dashboard and bundles it
into the wheel under `nengok/server/static/`.

This is the same pattern arize-phoenix uses: the React/Vite source lives
in a sibling `frontend/` directory during development, and at wheel-build
time we run `npm ci && npm run build` and copy the output into the
Python package so `nengok dashboard` can serve it from the installed
location without requiring Node on the user's machine.

Knobs:

* `NENGOK_SKIP_FRONTEND_BUILD=1`. Skip the build entirely. Useful when
  iterating on Python-only changes during editable installs, or when
  building a wheel on a machine without Node (the resulting wheel will
  serve API routes only).
* If `npm` is not on PATH during a wheel build, the hook hard-fails;
  shipping a wheel without the dashboard is almost never what we want.
  For editable installs we degrade to a warning so Python-only dev still
  works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

ROOT = Path(__file__).parent.resolve()
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
STATIC_DIR = ROOT / "nengok" / "server" / "static"


class FrontendBuildHook(BuildHookInterface):
    PLUGIN_NAME = "frontend"

    def initialize(self, _version: str, _build_data: dict[str, Any]) -> None:
        if self.target_name not in ("wheel", "editable"):
            return

        if os.environ.get("NENGOK_SKIP_FRONTEND_BUILD") == "1":
            self.app.display_info("NENGOK_SKIP_FRONTEND_BUILD=1 set; skipping dashboard build.")
            return

        if not FRONTEND_DIR.exists():
            self.app.display_warning(
                f"Frontend source not found at {FRONTEND_DIR}; skipping dashboard build."
            )
            return

        npm = shutil.which("npm")
        if npm is None:
            if self.target_name == "wheel":
                raise RuntimeError(
                    "npm not found on PATH but is required to build the Nengok dashboard "
                    "for the wheel. Install Node.js, or set NENGOK_SKIP_FRONTEND_BUILD=1 "
                    "to skip (the resulting wheel will serve API routes only)."
                )
            self.app.display_warning("npm not on PATH; skipping dashboard build for editable install.")
            return

        self.app.display_info(f"Building Nengok dashboard via npm in {FRONTEND_DIR}...")
        install_cmd = "ci" if (FRONTEND_DIR / "package-lock.json").exists() else "install"
        subprocess.run([npm, install_cmd], cwd=FRONTEND_DIR, check=True)
        subprocess.run([npm, "run", "build"], cwd=FRONTEND_DIR, check=True)

        if not DIST_DIR.exists():
            raise RuntimeError(f"Expected Vite build output at {DIST_DIR}, but it does not exist.")

        if STATIC_DIR.exists():
            shutil.rmtree(STATIC_DIR)
        shutil.copytree(DIST_DIR, STATIC_DIR)
        self.app.display_info(f"Bundled dashboard into {STATIC_DIR}.")
