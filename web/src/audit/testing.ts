import type { AuditEvent } from "./actions";

/** An audit entry with test defaults: a run started by a user. */
export function auditEvent(overrides: Partial<AuditEvent> = {}): AuditEvent {
  return {
    id: 1,
    at: "2026-10-26T10:00:00Z",
    action: "run.created",
    actor: { type: "user", id: null },
    run_id: "1a2b3c4d-0000-4000-8000-000000000001",
    node_id: null,
    details: { template_id: "generate-docs", repo_url: null, budget_usd: null },
    run: {
      template_id: "generate-docs",
      repo_url: "https://github.com/acme/docs",
      status: "completed",
    },
    ...overrides,
  };
}
