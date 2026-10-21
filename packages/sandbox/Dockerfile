# The sandbox image runs' repo tools execute in: alpine with git, so writer nodes can commit on
# their own worktree. Containers from it run as uid 1000 with no network, a read-only root and no
# capabilities (`agentic_sandbox.docker_backend`). Build: docker build -t agentic-dev/sandbox:dev packages/sandbox
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

RUN apk add --no-cache git \
    && adduser -D -u 1000 -h /tmp sandbox

# No system or user git config is read: every git call sets what it needs on its command line.
ENV GIT_CONFIG_NOSYSTEM=1 \
    GIT_CONFIG_GLOBAL=/dev/null \
    HOME=/tmp

USER 1000:1000
