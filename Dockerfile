# Swing live site: the broadcast screen with its prebuilt match bundles, plus "Generate match",
# which generates a brand-new match and plays it through the agents on Microsoft Foundry one minute
# at a time (swing/live). The app signs in to Foundry with its managed identity.
FROM mcr.microsoft.com/azurelinux/base/python:3.12
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY swing/ swing/
COPY data/league.json data/league.json
RUN (python3 -m pip --version || python3 -m ensurepip) && python3 -m pip install --no-cache-dir -e ".[foundry]"
COPY web/ web/
ENV SWING_STATE_DIR=/tmp/swing PYTHONUNBUFFERED=1
USER 10001
EXPOSE 8000
CMD ["swing-live", "--web", "web", "--port", "8000"]
