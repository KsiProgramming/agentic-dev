# The NuGet egress proxy (4.8): the only route out for a sandbox's .NET restore job. tinyproxy
# forwards `CONNECT` on port 443 to the hosts in `allow` and refuses everything else, logging the
# refused host. Job containers reach it on an internal Docker network (`agentic-nuget`) that has
# no other way out; the proxy alone is also on a network with internet access.
# Build: docker build -t agentic-dev/egress-proxy:dev packages/egress-proxy
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

ARG TINYPROXY_VERSION=1.11.2-r0
RUN apk add --no-cache "tinyproxy=${TINYPROXY_VERSION}"

COPY tinyproxy.conf /etc/tinyproxy/tinyproxy.conf
COPY allow /etc/tinyproxy/allow

USER tinyproxy
EXPOSE 3128
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
