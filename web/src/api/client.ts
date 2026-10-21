import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** Where the browser reaches the platform API. */
export function apiBaseUrl() {
  return process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
}

/** Typed client for the platform API. Types are generated from its OpenAPI spec (`pnpm gen:api`). */
export function createApiClient(baseUrl = apiBaseUrl()) {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;
