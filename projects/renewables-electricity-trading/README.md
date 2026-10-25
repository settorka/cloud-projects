# Renewables electricity trading

Versioned implementations of the GB renewable electricity trading backend.

| Folder | Purpose | Status |
|---|---|---|
| [v1](v1/README.md) | Local Docker Compose implementation | Existing implementation moved intact |
| [v2](v2/README.md) | AWS development deployment | Baseline copy follows in the next commit |
| [v3](v3/README.md) | Production deployment readiness | Planning placeholder |

Run commands from the selected version directory, not this project index. V1 owns its dependencies, containers, fixtures, tests and runbooks. AWS deployment has not been provisioned.

V1 is the local reference implementation. V2 will own its independent copy and evolve toward AWS development readiness. V3 has no application code yet. Changes are made to the intended version explicitly; directories are not runtime aliases or Python environments.
