# Cloud Run image for the hackathon hosted dashboard demo.
# In normal use, Nengok is `pip install`-ed locally — this image is only
# for the "hosted project URL" requirement of the hackathon submission.

FROM node:22-alpine AS frontend
WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.11-slim AS runtime
WORKDIR /app

# Node lives in the runtime stage, not only the frontend build stage: the
# ADK triage agent's MCP toolset spawns `npx @arizeai/phoenix-mcp` as a
# subprocess at runtime. Node 22 is the pinned LTS major (NodeSource).
# Verify with `docker run --rm <image> npx --version` before pushing.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md hatch_build.py ./
COPY nengok/ ./nengok/
COPY sample_agent/ ./sample_agent/

COPY --from=frontend /frontend/dist ./nengok/server/static

ENV NENGOK_SKIP_FRONTEND_BUILD=1
# `gemini` pulls google-genai so the dashboard's /health Gemini probe works and
# the image can route Gemini through Vertex AI (ADC) when deployed. `adk` pulls
# the pinned google-adk for the triage agent at the head of every cycle.
# `slack` pulls slack-bolt so /slack/events can mount for approval buttons.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[phoenix,server,gemini,adk,slack]"

# Pre-warm the npx cache with the pinned Phoenix MCP package (keep the pin in
# sync with DEFAULT_MCP_PACKAGE in nengok/config.py) so the first triage on a
# cold instance does not pay the full download. A nonzero exit only means the
# first cycle downloads at runtime, so it must not fail the build.
RUN npx -y @arizeai/phoenix-mcp@4.0.13 --help >/dev/null 2>&1 \
    || echo "phoenix-mcp pre-warm exited nonzero; first triage will download it"

ENV NENGOK_DASHBOARD_HOST=0.0.0.0 \
    NENGOK_DASHBOARD_PORT=8765

EXPOSE 8765

# Host/port come from NENGOK_DASHBOARD_HOST/PORT (set above). The dashboard
# command exposes --listen, not --host, so passing --host here would error.
CMD ["nengok", "dashboard", "--no-browser"]
