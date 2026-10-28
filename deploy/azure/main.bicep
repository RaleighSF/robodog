// Watch Dog telemetry ingest for Ignite: Event Hubs namespace + hub.
// Deployed into an existing resource group (see deploy.sh). ADX (free
// cluster) is created in its web UI and connected to this hub; it cannot be
// declared here (free clusters have no ARM resource).
@description('Azure region')
param location string = resourceGroup().location

@description('Globally unique Event Hubs namespace name')
param namespaceName string

@description('Event hub (topic) name - must match telemetry.azure_eventhub.eventhub_name on the Thor')
param eventHubName string = 'watchdog-telemetry'

@allowed(['Basic', 'Standard'])
param sku string = 'Basic'

resource ns 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: namespaceName
  location: location
  sku: { name: sku, tier: sku, capacity: 1 }
  properties: {
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false   // SAS keys: the Thor sends with a send-only key
  }
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = {
  parent: ns
  name: eventHubName
  properties: {
    partitionCount: 2
    messageRetentionInDays: 1   // ADX is the store; the hub only buffers
  }
}

// Least privilege: the edge can only SEND; ADX can only LISTEN.
resource edgeSend 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: hub
  name: 'edge-send'
  properties: { rights: ['Send'] }
}

resource adxListen 'Microsoft.EventHub/namespaces/eventhubs/authorizationRules@2024-01-01' = {
  parent: hub
  name: 'adx-listen'
  properties: { rights: ['Listen'] }
}

output namespace string = ns.name
output eventHub string = hub.name
output edgeSendRule string = edgeSend.name
output adxListenRule string = adxListen.name
