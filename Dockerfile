# MatchLens live site: the broadcast screen and its prebuilt match bundles, served as static files.
# The agents ran on Microsoft Foundry when the bundles in web/data were built
# (matchlens-broadcast --demo 6 --agents foundry), so viewers never trigger a model call.
FROM mcr.microsoft.com/azurelinux/base/python:3.12
WORKDIR /site
COPY web/ ./
USER 10001
EXPOSE 8000
CMD ["python3", "-m", "http.server", "8000", "--bind", "0.0.0.0"]
