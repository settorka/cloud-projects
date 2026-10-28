# cloud-projects

Independent applications, each owning its code, dependencies, tests and deployment configuration.

| Project | Description | Status |
|---|---|---|
| [renewables-electricity-trading](projects/renewables-electricity-trading/README.md) | GB renewable electricity trade booking, exposure and valuation | Versioned: V1 local, V2 AWS dev, V3 production plan |
| [maritime-intelligence](projects/maritime-intelligence/README.md) | Real AIS ingestion, vessel history and evidence-based port visits | V1 Compose; V2 Terraform and Lambda deployment configuration |

Applications live under `projects/<name>/`. Existing AWS OIDC diagnostics are under `.github/workflows`; no cloud resources are provisioned by the local project.
