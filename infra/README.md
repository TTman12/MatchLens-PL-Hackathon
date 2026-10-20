# infra

MatchLens live on **Azure Container Apps**, next to the Microsoft Foundry project.

| Piece | What it does |
| --- | --- |
| `Dockerfile` (repo root) | Player and live server in one image on Azure Linux base images. The featured match is simulated at build time; the agents run on Foundry at view time. |
| `.github/workflows/image.yml` | Builds the image on every push and publishes it to `ghcr.io/ttman12/matchlens-pl-hackathon/live:<sha>` (public). |
| `main.bicep` | Container App (scale 0 to 1), its managed identity with **Azure AI User** on the Foundry account and **Storage Blob Data Contributor** on a small storage account for replay state, logs to the existing Log Analytics workspace, agent traces to the existing Application Insights, and a monthly budget alert. |

No keys or secrets: the app signs in to Foundry and Storage with its managed identity.

## Cost controls

- The app scales to zero between viewers, so hosting stays inside the Container Apps
  free monthly grant. The first visit after a quiet spell takes a few seconds longer.
- One replica at most: the match clock lives in memory, so every viewer shares one match.
- `ReplayProvider` remembers every model answer in the replay blob, so replaying the
  match calls the model again only for tasks it has not seen.
- `MATCHLENS_DAILY_MODEL_CALLS` (default 850, about 5 full matches) caps model calls a
  day; past it, unseen tasks get the offline templates.
- A $20 monthly budget on the resource group emails at 50% spent and at a forecast of 100%.

## Deploy

```bash
az login
az provider register -n Microsoft.App --wait
az provider register -n Microsoft.Storage --wait
az deployment group create -g rg-tristan.friend.12-4381 -f infra/main.bicep \
  -p image=ghcr.io/ttman12/matchlens-pl-hackathon/live:<commit sha> budgetEmail=<email>
```

The output `url` is the public link; a bare link opens the live match.
