// MatchLens live on Azure Container Apps, next to the Microsoft Foundry project.
//
// One container app serves the match player and the live server. It scales to zero
// between viewers and to at most one replica while watched (the match clock lives in
// memory). Its managed identity calls the Foundry model, and keeps the agents' replay
// state in a blob so a looping match pays the model once and the daily cap survives
// restarts. No keys or secrets anywhere.
//
//   az deployment group create -g <foundry resource group> -f infra/main.bicep \
//     -p image=ghcr.io/ttman12/matchlens-pl-hackathon/live:<sha> budgetEmail=<you>

@description('Container image to run.')
param image string

@description('Name of the existing Foundry (AI Services) account in this resource group.')
param foundryAccountName string = 'matchlens-foundry-812'

@description('Foundry project inside that account.')
param foundryProjectName string = 'matchlens'

@description('Model deployment the agents use (fast and strong).')
param model string = 'gpt-4.1-mini'

@description('Most agent tasks a day that may reach the model. About 170 is one full match.')
param dailyModelCalls int = 850

@description('Existing Log Analytics workspace for the app logs.')
param logAnalyticsName string = 'matchlens-foundry-812-logs'

@description('Existing Application Insights linked to the Foundry project, for agent traces.')
param appInsightsName string = 'matchlens-foundry-812-appinsights'

@description('Monthly budget for this resource group, in the billing currency.')
param budgetAmount int = 20

@description('Who gets the budget alert emails.')
param budgetEmail string

@description('First day of the budget period (yyyy-MM-01).')
param budgetStart string = '${utcNow('yyyy-MM')}-01'

param location string = resourceGroup().location
param name string = 'matchlens-live'

var suffix = uniqueString(resourceGroup().id, name)
var azureAiUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d'
var storageBlobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' existing = {
  name: foundryAccountName
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsName
}

resource insights 'Microsoft.Insights/components@2020-02-02' existing = {
  name: appInsightsName
}

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: 'mlreplay${suffix}'
  location: location
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobs 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource replay 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobs
  name: 'replay'
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
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: [
            { name: 'MATCHLENS_PROVIDER', value: 'foundry' }
            {
              name: 'AZURE_AI_PROJECT_ENDPOINT'
              value: 'https://${foundryAccountName}.services.ai.azure.com/api/projects/${foundryProjectName}'
            }
            { name: 'AZURE_AI_MODEL_FAST', value: model }
            { name: 'MATCHLENS_DAILY_MODEL_CALLS', value: string(dailyModelCalls) }
            {
              name: 'MATCHLENS_REPLAY_BLOB_URL'
              value: '${storage.properties.primaryEndpoints.blob}replay/m291.json'
            }
            { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: insights.properties.ConnectionString }
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
        minReplicas: 0
        maxReplicas: 1
        rules: [
          { name: 'http', http: { metadata: { concurrentRequests: '100' } } }
        ]
      }
    }
  }
}

resource canUseModel 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, app.id, azureAiUser)
  scope: foundry
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUser)
  }
}

resource canKeepReplay 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.id, app.id, storageBlobDataContributor)
  scope: storage
  properties: {
    principalId: app.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      storageBlobDataContributor
    )
  }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
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
