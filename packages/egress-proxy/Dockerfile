# The package egress proxy (4.8, 13.2): the only route out for a sandbox's restore job. tinyproxy
# forwards `CONNECT` on port 443 to the hosts in one registry's allow file and refuses everything
# else, logging the refused host. One image, one config per registry (`nuget`, `npm`, `pypi`), one
# container and one internal Docker network per registry (`agentic-nuget`, ...) that has no other
# way out; the proxy alone is also on a network with internet access. The default is NuGet's.
# Build: docker build -t agentic-dev/egress-proxy:dev packages/egress-proxy
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

ARG TINYPROXY_VERSION=1.11.2-r0
RUN apk add --no-cache "tinyproxy=${TINYPROXY_VERSION}"

COPY *.conf *.allow /etc/tinyproxy/

USER tinyproxy
EXPOSE 3128
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/nuget.conf"]
