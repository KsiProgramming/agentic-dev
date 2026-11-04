# Security policy

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub: go to the repository's **Security** tab and choose **Report a vulnerability** ([direct link](../../security/advisories/new)). The report is visible only to the maintainers.

Please include:

- the affected component (API, worker, sandbox, web, a package) and version or commit;
- the impact and the conditions needed (for example "requires network access to the API");
- steps to reproduce or a proof of concept;
- any suggested fix.

What to expect:

| Step | Target |
|---|---|
| Acknowledgement | within 3 business days |
| First assessment (confirmed or not, severity) | within 10 business days |
| Fix or mitigation for confirmed high or critical issues | as fast as possible, coordinated with you |
| Public advisory | once a fix is released, crediting you unless you prefer otherwise |

This is a community project maintained on a best-effort basis; the targets above are commitments of intent, not a contractual SLA.

## Supported versions

The project is pre-1.0. Security fixes are made on `main` and included in the next release. Older releases are not patched.

## Scope

In scope: code in this repository, the container images it builds, and the documented default configuration.

**Known limitations are not vulnerabilities** but are welcome as hardening contributions. They are listed in the [security model](docs/security/security-model.md#7-known-gaps-and-hardening-roadmap). The most important: **the API has no user authentication yet**, so it must only be exposed behind an authenticating proxy on a private network.

Out of scope: denial of service through volume alone, findings that need an already compromised host or database, and vulnerabilities in third-party services (GitHub, model providers). Report those to their owners.

## Safe harbour

Good-faith research that follows this policy, avoids privacy violations and service disruption, and uses only your own deployments and accounts will not be pursued. Never test against a deployment you do not own.
