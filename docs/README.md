# Documentation

| I want to… | Read |
|---|---|
| Understand what the platform is for and how people use it | [Business flows](architecture/business-flows.md), [Product specification](product/product-spec.md), [Mission](../specs/mission.md) |
| Understand how it is built | [Architecture overview](architecture/overview.md), [Technical flows](architecture/technical-flows.md), [Data model](architecture/data-model.md) |
| Know why it is built this way | [Architecture decisions](architecture/decisions.md) and the full log in [`specs/tech-stack.md`](../specs/tech-stack.md#decisions-log) |
| Assess its security | [Security model](security/security-model.md), [SECURITY.md](../SECURITY.md) |
| Deploy and operate it | [Deployment guide](operations/deployment.md), [Configuration reference](operations/configuration.md) |
| Connect my GitHub and model provider, or add a new integration | [Connecting your platforms](integrations/connecting-platforms.md) |
| Contribute code | [Getting started](development/getting-started.md), [Developer reference](development/developer-reference.md), [CONTRIBUTING.md](../CONTRIBUTING.md) |
| See what is built and what is next | [Roadmap](../specs/roadmap.md), [Changelog](../CHANGELOG.md) |

## How documentation relates to `specs/`

`specs/` is the **binding** source: mission and principles, the roadmap, the tech stack with every API contract and decision, the design language, and one folder per planned phase. The documents in `docs/` **explain** the system to readers who were not part of building it. When the two disagree, `specs/` wins, and the doc is fixed in the same pull request that notices it.

## Layout

```
docs/
├── architecture/
│   ├── overview.md          C4 context, containers, components, qualities
│   ├── business-flows.md    actors, value stream, user flows
│   ├── technical-flows.md   run lifecycle, durability, gates, PRs, streaming, secrets
│   ├── data-model.md        tables, relationships, invariants
│   └── decisions.md         architecture decision records
├── security/
│   └── security-model.md    assets, trust boundaries, STRIDE, controls, known gaps
├── operations/
│   ├── deployment.md        local, single host, production reference, operations
│   └── configuration.md     every environment variable
├── integrations/
│   └── connecting-platforms.md   your GitHub App and model keys; extension points
├── development/
│   ├── getting-started.md   tools, stack, checks, first change
│   └── developer-reference.md    phase-by-phase reference and demos
└── product/
    └── product-spec.md      the original product and technical specification
```
