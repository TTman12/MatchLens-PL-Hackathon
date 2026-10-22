# infra

Swing on Azure, as code. Everything runs in one resource group, next to the Microsoft Foundry project.

| File | What it does |
| --- | --- |
| `main.bicep` | Sets up the live site on **Azure Container Apps**: one container that scales to zero, with `/healthz` probes and logs going to **Log Analytics**. The app gets a managed identity with **Azure AI User** on the Foundry account. The `matchlens-ci` service principal gets **Contributor on the app only** (to deploy) and **Azure AI Developer** on the Foundry account (to run evaluations). It also adds a monthly **budget** alert. |
| `foundry.bicep` | Only used with `newFoundry=true`. Creates the **Foundry** (AI Services) account with key-based auth turned off, a project, the `gpt-4.1-mini` deployment, and **Application Insights** connected to the project, so agent traces show on its Tracing page. |
| `main.parameters.json` | The parameters, filled in from environment variables (the `azd` convention). |
| `../azure.yaml` | **Azure Developer CLI** project: `azd provision` runs `main.bicep`. |

## How changes reach Azure

- **Site:** a merge to `main` that touches `web/` triggers `.github/workflows/image.yml`, which builds the image and pushes it to GHCR. `deploy.yml` then signs in with **OpenID Connect** (a federated credential on `matchlens-ci`, with no secret) and rolls the container app to that image. It checks `/healthz` before the run counts as passed.
- **Infra:** `infra.yml` compiles and lints the templates on every PR. Applying them is a manual step (below), because the CI principal is only allowed to touch the one app.

## Apply

```bash
# the existing environment: pass the image that is live, so the site stays as it is
az deployment group create -g rg-tristan.friend.12-4381 -f infra/main.bicep \
  -p image=ghcr.io/ttman12/matchlens-pl-hackathon/live:<sha> budgetEmail=<email> \
     ciPrincipalId=$(az ad sp show --id 519837f7-fa8b-46b8-b6d0-1d6932fecf14 --query id -o tsv)

# a new environment from nothing
azd env new swing-dev && azd env set AZURE_LOCATION eastus2
azd env set SWING_NEW_FOUNDRY true && azd env set SWING_FOUNDRY <globally unique name>
azd provision
```

Applying the template is safe to repeat: resources it doesn't name are left alone (incremental mode).

## Cost controls

- The app scales to zero between viewers, so hosting stays inside the Container Apps free monthly grant. It runs at 0.25 vCPU and 0.5 GiB.
- Viewers never trigger a model call. The match bundles are built on Foundry ahead of time, for about 5 cents a match.
- The Log Analytics workspace that `newFoundry` creates is capped at 1 GB a day.
- The $20 monthly budget on the resource group emails at 50% actual spend and at a 100% forecast.
