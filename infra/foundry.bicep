// A fresh Microsoft Foundry setup for MatchLens: an AI Services account with a project, the
// gpt-4.1-mini deployment the agents use, and Application Insights connected to the project so
// agent runs show on its Tracing page. Only used for a new environment (main.bicep newFoundry);
// the live one already has all of this.

param name string
param projectName string
param model string
param modelVersion string
param capacity int
param logAnalyticsId string
param location string = resourceGroup().location

resource account 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: name
  location: location
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: name
    allowProjectManagement: true
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: true // Entra ID only: no keys
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: account
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {}
}

resource deployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: account
  name: model
  sku: { name: 'GlobalStandard', capacity: capacity }
  properties: {
    model: { format: 'OpenAI', name: model, version: modelVersion }
  }
}

resource insights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${name}-appinsights'
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsId
  }
}

resource tracing 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: insights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: { key: insights.properties.ConnectionString }
    metadata: { ApiType: 'Azure', ResourceId: insights.id }
  }
}

output accountId string = account.id
output endpoint string = 'https://${name}.services.ai.azure.com/api/projects/${projectName}'
