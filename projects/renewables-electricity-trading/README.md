# Renewables electricity trading

Versioned implementations of the GB renewable electricity trading backend.

| Folder | Purpose | Status |
|---|---|---|
| [v1](v1/README.md) | Local Docker Compose implementation | Existing implementation moved intact |
| [v2](v2/README.md) | AWS development deployment | Independent V1 baseline copy; AWS work pending |
| [v3](v3/README.md) | Production deployment readiness | Planning placeholder |

Run commands from the selected version directory, not this project index. V1 owns its dependencies, containers, fixtures, tests and runbooks. AWS deployment has not been provisioned.

V1 is the local reference implementation. V2 will own its independent copy and evolve toward AWS development readiness. V3 has no application code yet. Changes are made to the intended version explicitly; directories are not runtime aliases or Python environments.

## Local use

```sh
cd v1    # Preserved local implementation: ports 8001–8003
make up
```

Or, from the project root:

```sh
cd v2    # Independent development baseline: ports 8101–8103
make up
```

Each version owns its Compose files, uv environments, dependency locks, schemas, fixtures, tests and runbooks. V2 copies tracked source only. Changes and security fixes must be evaluated explicitly for each maintained version; there is no automatic synchronization. V3 is a documented placeholder, not a production deployment.

Git commits remain the change history. These folders name runnable development milestones; they are not API version numbers.
