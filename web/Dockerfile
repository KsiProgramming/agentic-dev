# Build context: web/

FROM node:24-alpine AS base
RUN npm install -g pnpm@11.11.0

FROM base AS build
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 HOSTNAME=0.0.0.0 PORT=3000
COPY --from=build --chown=node:node /app/.next/standalone ./
COPY --from=build --chown=node:node /app/.next/static ./.next/static
USER node
EXPOSE 3000

HEALTHCHECK --interval=5s --timeout=3s --start-period=10s --retries=10 \
    CMD ["wget", "-qO-", "http://127.0.0.1:3000/"]

CMD ["node", "server.js"]
