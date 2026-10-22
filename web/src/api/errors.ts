/** Reading the API's error bodies: FastAPI's `{detail}`, which is a string, a `{code, message}`
 * object (our own refusals) or a list of validation errors (422). */

/** One FastAPI validation error: where (`loc`) and why (`msg`). */
export interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
}

export function detailOf(error: unknown): unknown {
  return error && typeof error === "object" && "detail" in error ? error.detail : null;
}

/** The `code` of a `{detail: {code, message}}` body, or null. */
export function codeOf(error: unknown): string | null {
  const detail = detailOf(error);
  if (detail && typeof detail === "object" && "code" in detail && typeof detail.code === "string") {
    return detail.code;
  }
  return null;
}

/** What the body says for people: a string detail, a `{message}`, or the first validation
 * error's `msg`. Null when it says nothing usable. */
export function messageOf(error: unknown): string | null {
  const detail = detailOf(error);
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && "message" in detail) {
    return typeof detail.message === "string" ? detail.message : null;
  }
  const [first] = validationIssues(error);
  return first?.msg ?? null;
}

/** The validation errors of a 422 body (empty for any other body). */
export function validationIssues(error: unknown): ValidationIssue[] {
  const detail = detailOf(error);
  if (!Array.isArray(detail)) return [];
  return detail.flatMap((item: unknown) => {
    if (!item || typeof item !== "object" || !("loc" in item) || !("msg" in item)) return [];
    const { loc, msg } = item;
    if (!Array.isArray(loc) || typeof msg !== "string") return [];
    return [{ loc: loc.filter((p) => typeof p === "string" || typeof p === "number"), msg }];
  });
}

/** A thrown fetch error for people: the network, or the error's own message. */
export function failure(err: unknown): string {
  if (err instanceof TypeError) return "Could not reach the API.";
  return err instanceof Error ? err.message : String(err);
}

/** A non-2xx answer, with what its body said. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly body: unknown,
    fallback: string,
  ) {
    super(messageOf(body) ?? `${fallback} (HTTP ${status}).`);
    this.name = "ApiError";
  }

  get code(): string | null {
    return codeOf(this.body);
  }
}
