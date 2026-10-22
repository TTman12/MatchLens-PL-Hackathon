// Swing on Azure: the live site on Azure Container Apps, next to the Microsoft Foundry project
// the agents run on.
//
// The live site is the broadcast screen and its prebuilt match bundles, served from one container
// that scales to zero between viewers. GitHub Actions rolls it to each new image (deploy.yml) as
// the matchlens-ci service principal, which may change only this app. A monthly budget on the
// resource group emails before spend gets near the limit.
//
// Against the existing environment (the default) it reuses the Foundry account, its Log Analytics
// workspace and Application Insights. With newFoundry=true it creates all of them as well, so the
// whole thing can be stood up from nothing:
//
//   az deployment group create -g <resource group> -f infra/main.bicep -p image=<image> ...   (infra/README.md)
//   azd provision        (the same, through the Azure Developer CLI; see azure.yaml)

@description('Container image to run. Pass the one that is live to leave the site as it is.')
param image string = 'ghcr.io/ttman12/matchlens-pl-hackathon/live:latest'

param name string = 'matchlens-live'
param location string = resourceGroup().location

@description('Create a new Foundry account, project, model deployment and Application Insights.')
param newFoundry bool = false

@description('Foundry (AI Services) account in this resource group: existing, or to create.')
param foundryAccountName string = 'matchlens-foundry-812'

param foundryProjectName string = 'matchlens'

@description('Model deployment the agents use.')
param model string = 'gpt-4.1-mini'
param modelVersion string = '2025-04-14'

@description('Model capacity in thousands of tokens a minute (new Foundry only).')
param modelCapacity int = 50

@description('Log Analytics workspace for the app logs: existing, or to create with newFoundry.')
param logAnalyticsName string = '${foundryAccountName}-logs'

@description('Object id of the matchlens-ci service principal. Empty skips its role grants.')
param ciPrincipalId string = ''

@description('Monthly budget for this resource group, in the billing currency.')
param budgetAmount int = 20

@description('Who gets the budget alert emails. Empty skips the budget.')
param budgetEmail string = ''

@description('First day of the budget period (yyyy-MM-01). Keep it fixed once the budget exists.')
param budgetStart string = '2026-10-01'

var contributor = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
var azureAiUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var azureAiDeveloper = '64702f94-c441-49e6-a78b-ef80e0188fee'

resource logsNew 'Microsoft.OperationalInsights/workspaces@2023-09-01' = if (newFoundry) {
  name: logAnalyticsName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: 1 } // logs can never run up the bill
  }
}

module foundryNew 'foundry.bicep' = if (newFoundry) {
  name: 'foundry'
  params: {
    name: foundryAccountName
    projectName: foundryProjectName
    model: model
    modelVersion: modelVersion
    capacity: modelCapacity
    logAnalyticsId: logsNew.id
    location: location
  }
}

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
  dependsOn: [foundryNew]
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
  dependsOn: [logsNew]
}

resource env 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${name}-env'
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource app 'Microsoft.App/containerApps@2024-03-01' = {
  name: name
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    managedEnvironmentId: env.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'live'
          image: image
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
          env: [
            {
              name: 'AZURE_AI_PROJECT_ENDPOINT'
              value: 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'
            }
            { name: 'AZURE_AI_MODEL', value: model }
            { name: 'SWING_DAILY_AI_MATCHES', value: '10' } // Generate match: AI-explained matches a day
            { name: 'SWING_DAILY_MODEL_CALLS', value: '1700' }
          ]
          probes: [
            {
              type: 'Startup'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 2
              failureThreshold: 30
            }
            {
              type: 'Liveness'
              httpGet: { path: '/healthz', port: 8000 }
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 0 // free between viewers; the first visit after a quiet spell takes a few seconds
        maxReplicas: 1
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '100' } } }
        ]
      }
    }
  }
}

// The app's identity calls the Foundry project when a viewer presses Generate match.
resource appUsesFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, app.id, azureAiUser)
  scope: foundry
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUser)
  }
}

// GitHub Actions (OIDC as matchlens-ci): roll this app to a new image, and run Foundry evaluations.
resource ciDeploys 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ciPrincipalId)) {
  name: guid(app.id, ciPrincipalId, contributor)
  scope: app
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributor)
  }
}

resource ciUsesFoundry 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(ciPrincipalId)) {
  name: guid(foundry.id, ciPrincipalId, azureAiDeveloper)
  scope: foundry
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiDeveloper)
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (!empty(budgetEmail)) {
  name: '${name}-budget'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStart }
    notifications: {
      actual50: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 50
        thresholdType: 'Actual'
        contactEmails: [budgetEmail]
      }
      forecast100: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 100
        thresholdType: 'Forecasted'
        contactEmails: [budgetEmail]
      }
    }
  }
}

output url string = 'https://${app.properties.configuration.ingress.fqdn}'
output foundryEndpoint string = 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'
