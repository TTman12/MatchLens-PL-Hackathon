# MatchLens live: the match player and the live server in one image.
# The featured match is simulated at build time; the agents run at view time, on
# Microsoft Foundry when AZURE_AI_PROJECT_ENDPOINT is set, offline otherwise.
# Base images come from the Microsoft Container Registry (Azure Linux).

FROM mcr.microsoft.com/azurelinux/base/nodejs:24 AS web
WORKDIR /src/web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM mcr.microsoft.com/azurelinux/base/python:3.12
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PATH=/opt/venv/bin:$PATH
RUN python3 -m venv /opt/venv
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY matchlens ./matchlens
COPY schemas ./schemas
RUN pip install ".[live,foundry]"
COPY data/season ./data/season
RUN matchlens-demo --no-agents --out data/demo
COPY --from=web /src/web/dist ./web/dist
USER 10001
EXPOSE 8000
CMD ["matchlens-live", "data/demo", "--web", "web/dist", "--host", "0.0.0.0", "--port", "8000", "--loop", "60"]
