# The sandbox image runs' repo tools execute in: alpine with git, so writer nodes can commit on
# their own worktree, the scanners of the `scan` tools (4.4) and the .NET SDK `scan.lint` builds
# C# projects with (4.8). Containers from it run as uid 1000 with no network, a read-only root and
# no capabilities (`agentic_sandbox.docker_backend`); only a .NET restore job reaches NuGet,
# through the egress proxy (`packages/egress-proxy`).
# Build: docker build -t agentic-dev/sandbox:dev packages/sandbox

# Scanners: pinned releases, each checked against its sha256 (from the release's asset digest).
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc AS scanners
ARG TARGETARCH
ARG RUFF_VERSION=0.17.0
ARG BIOME_VERSION=2.5.15
ARG SHELLCHECK_VERSION=0.11.0
ARG GITLEAKS_VERSION=8.30.1
ARG OSV_SCANNER_VERSION=2.7.0
RUN apk add --no-cache curl xz
WORKDIR /dl
RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) ruff=x86_64; biome=x64; sc=x86_64; gl=x64; osv=amd64; \
        ruff_sha=0df9421fd0df9aa7a62dab4d1086e085b7c7888b6343fc5a9c5f630771d61aae; \
        biome_sha=42b6fd3662fc1fc3075a370414478aa3ed82fd43d28430bbfb81ebd02cbde656; \
        sc_sha=8c3be12b05d5c177a04c29e3c78ce89ac86f1595681cab149b65b97c4e227198; \
        gl_sha=551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb; \
        osv_sha=160c6253e2922e9e0a6a9771c5c4c40a4b3c6090b34a3cdd5e80c96cc2e4218b ;; \
      arm64) ruff=aarch64; biome=arm64; sc=aarch64; gl=arm64; osv=arm64; \
        ruff_sha=cac779097e34bf1ca40175b4bacf8fca7a92fce5030bfc3edf1fd357428a33b0; \
        biome_sha=195d4525282d2b877357ba8377545061e342808da37997051153708c7b5326fa; \
        sc_sha=12b331c1d2db6b9eb13cfca64306b1b157a86eb69db83023e261eaa7e7c14588; \
        gl_sha=e4a487ee7ccd7d3a7f7ec08657610aa3606637dab924210b3aee62570fb4b080; \
        osv_sha=4061ef4c021ed3c47f203b818f337e351336cc5cd67c0274fc36bd1dfc728dd7 ;; \
      *) echo "unsupported arch: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    get() { curl -fsSL --retry 3 -o "$1" "$2" && echo "$3  $1" | sha256sum -c -; }; \
    get ruff.tgz "https://github.com/astral-sh/ruff/releases/download/${RUFF_VERSION}/ruff-${ruff}-unknown-linux-musl.tar.gz" "$ruff_sha"; \
    get biome "https://github.com/biomejs/biome/releases/download/%40biomejs%2Fbiome%40${BIOME_VERSION}/biome-linux-${biome}-musl" "$biome_sha"; \
    get sc.txz "https://github.com/koalaman/shellcheck/releases/download/v${SHELLCHECK_VERSION}/shellcheck-v${SHELLCHECK_VERSION}.linux.${sc}.tar.xz" "$sc_sha"; \
    get gl.tgz "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_${gl}.tar.gz" "$gl_sha"; \
    get osv-scanner "https://github.com/google/osv-scanner/releases/download/v${OSV_SCANNER_VERSION}/osv-scanner_linux_${osv}" "$osv_sha"; \
    mkdir bin; \
    tar -xzf ruff.tgz --strip-components=1 -C bin "ruff-${ruff}-unknown-linux-musl/ruff"; \
    tar -xJf sc.txz --strip-components=1 -C bin "shellcheck-v${SHELLCHECK_VERSION}/shellcheck"; \
    tar -xzf gl.tgz -C bin gitleaks; \
    install -m 0755 biome osv-scanner bin/; \
    chmod 0755 bin/*

# The OSV vulnerability database for offline scans (the sandbox has no network), in the layout
# osv-scanner 2 reads: `<dir>/osv-scalibr/<ecosystem>/all.zip` (its docs still say
# `osv-scanner/`). Its date, in /opt/osv/as-of, is reported by `scan.dependencies`; a new image
# refreshes it.
FROM scanners AS osv-db
ARG OSV_ECOSYSTEMS="PyPI npm Go crates.io Maven NuGet RubyGems Packagist"
RUN set -eu; \
    for e in $OSV_ECOSYSTEMS; do \
      mkdir -p "/osv/osv-scalibr/$e"; \
      curl -fsSL --retry 3 -o "/osv/osv-scalibr/$e/all.zip" \
        "https://osv-vulnerabilities.storage.googleapis.com/$e/all.zip"; \
    done; \
    date -u +%Y-%m-%d > /osv/as-of

# The .NET SDK (4.8): the current LTS for linux-musl, from Microsoft's image pinned by its index
# digest (amd64 and arm64). `scan.lint` builds C# projects with it to run their analyzers;
# reference packs for older target frameworks and the repo's analyzer packages come from NuGet
# when a restore job runs.
FROM mcr.microsoft.com/dotnet/sdk:10.0.403-alpine3.24@sha256:cc02b814237a76c4735fb6eeee87181597b5e56f2ce458a435e527674d91f4d7 AS dotnet

FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

# git for the repo tools; the rest is what the .NET SDK needs on alpine.
RUN apk add --no-cache git ca-certificates icu-libs krb5-libs libgcc libintl libssl3 libstdc++ zlib \
    && adduser -D -u 1000 -h /tmp sandbox

COPY --from=dotnet /usr/share/dotnet/ /usr/share/dotnet/
RUN ln -s /usr/share/dotnet/dotnet /usr/local/bin/dotnet
COPY --from=scanners /dl/bin/ /usr/local/bin/
COPY --from=osv-db /osv/ /opt/osv/
COPY scan/ /opt/scan/

# No system or user git config is read: every git call sets what it needs on its command line.
# Scanners keep no cache (the root is read-only; /tmp is small) and read the baked OSV database.
ENV GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    HOME=/tmp \
    RUFF_NO_CACHE=true \
    OSV_SCANNER_LOCAL_DB_CACHE_DIRECTORY=/opt/osv \
    DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    DOTNET_NOLOGO=1 \
    DOTNET_SKIP_FIRST_TIME_EXPERIENCE=1 \
    DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE=1 \
    DOTNET_GENERATE_ASPNET_CERTIFICATE=false \
    NUGET_CERT_REVOCATION_MODE=offline

USER 1000:1000
