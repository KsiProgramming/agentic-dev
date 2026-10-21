import createClient from "openapi-fetch";

import type { paths } from "./schema";

/** Typed client for the platform API. Types are generated from its OpenAPI spec (`pnpm gen:api`). */
export function createApiClient(
  baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
) {
  return createClient<paths>({ baseUrl });
}

export type ApiClient = ReturnType<typeof createApiClient>;
