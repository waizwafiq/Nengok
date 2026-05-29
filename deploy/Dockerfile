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

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md hatch_build.py ./
COPY nengok/ ./nengok/
COPY sample_agent/ ./sample_agent/

COPY --from=frontend /frontend/dist ./nengok/server/static

ENV NENGOK_SKIP_FRONTEND_BUILD=1
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ".[phoenix,server]"

ENV NENGOK_DASHBOARD_HOST=0.0.0.0 \
    NENGOK_DASHBOARD_PORT=8765

EXPOSE 8765

# Host/port come from NENGOK_DASHBOARD_HOST/PORT (set above). The dashboard
# command exposes --listen, not --host, so passing --host here would error.
CMD ["nengok", "dashboard", "--no-browser"]
