# Azure audit and decision

## Live read-only inventory: 2026-08-23

| Check | Observed result |
|---|---|
| Subscription | `Azure for Students`, Enabled, default |
| Offer/quota | `AzureForStudents_2018-01-01` |
| Spending limit | On |
| Resource groups | one: `NetworkWatcherRG` in Poland Central |
| Resources | one: regional `Microsoft.Network/networkWatchers` |
| Azure Resource Graph | `resourceCount = 1`, `totalRecords = 1` |
| Budgets | none |
| Month-to-date actual cost | **$0.987910368 USD** |

The cost breakdown attributes about $0.95150 to prior virtual-machine use, $0.03640 to
virtual networking, tiny bandwidth/storage amounts, and resource groups that are no
longer present in the current inventory. The current Network Watcher resource did not
appear as a cost row. This distinction matters: current resources and month-to-date
historical charges describe different things.

Exact remaining student credit and expiration were not available through the queried
management/cost APIs. Microsoft directs Azure for Students users to the
[Azure Sponsorships portal](https://www.microsoftazuresponsorships.com/balance) for the
balance and expiry date. The standard offer is $100 for 12 months, but this repository
does not infer the user's remaining balance from that headline or from month-to-date cost.

## Decision: no Azure runtime in v0.1

Azure adds no unique zero-cost value to the current ingestion workload:

- GitHub Actions already supplies enough scheduled compute;
- Neon is mandated and already provisioned as the persistent database;
- Azure Functions' execution grant applies to consumption subscriptions but its required
  storage account is billed separately, so “inside free executions” is not a $0 proof;
- Container Apps, VMs, Log Analytics, and storage all add metered surfaces or needless
  complexity;
- the subscription has no budget and already recorded nearly $1 of August usage.

Therefore v0.1 creates **no Azure resources** and has **$0 incremental Azure cost**.
The existing Network Watcher is left untouched. Network Watcher has free included units
for some diagnostics/logs, but optional flow logs, connection tests, and Log Analytics
can bill; the engine will not enable them.

## Reconsideration gates

Azure should be reconsidered only if one of these becomes true:

1. GitHub Actions cannot meet execution duration or scheduling reliability.
2. A temporary, bounded ML training job has a measured advantage over local execution.
3. The Sponsorships portal confirms enough unexpired credit and the user approves a
   costed experiment with cleanup and an explicit maximum loss.
4. An Azure service supplies a capability Neon/GitHub cannot provide at zero incremental
   cost.

Before any Azure write: re-run inventory and cost, verify quota/pricing by region, create
a $0/credit alert strategy where supported, define deletion/rollback, and obtain explicit
approval. A budget alert alone is not a hard spending stop; the subscription spending
limit is the stronger current safeguard.

Official references:

- [Azure for Students balance and lifecycle](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/azurestudents-subscription-disabled)
- [Azure spending limit](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/spending-limit)
- [Azure Functions pricing and storage caveat](https://azure.microsoft.com/en-us/pricing/details/functions/)
- [Network Watcher pricing](https://azure.microsoft.com/en-us/pricing/details/network-watcher/)
