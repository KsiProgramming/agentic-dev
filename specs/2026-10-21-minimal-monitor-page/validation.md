# Validation: Minimal monitor page: list events of a run

## Done when (from roadmap)
> Browser shows events within 1 s

Made checkable: for every event row of a live run, the time the browser rendered it minus the event's `created_at` (set by the database) is under 1000 ms, measured in Playwright against the compose stack.

## Automated checks
- [ ] Vitest `use-run-events.test.ts` (fake `EventSource`):
  - events arriving out of order are listed by `seq`, and a repeated `seq` is dropped;
  - status goes `connecting` → `live` → `completed` on `run_completed` (and `failed` / `cancelled`), and `close()` is called after a terminal event;
  - an `error` before any event, with a 404 probe, gives `not_found`;
  - unmount closes the `EventSource`.
- [ ] Vitest `summarize.test.ts`: `text_delta`, `usage`, `run_failed` and an unknown type each give the expected one-line text, and long payloads are truncated.
- [ ] Vitest `run-events.test.tsx`: rows render in order with `data-seq`, the status badge reflects status, the not-found state renders, and HTML in a payload is shown as literal text.
- [ ] Vitest `start-run-form.test.tsx`: a submit POSTs `{ workflow: sampleSpec, input }`, navigates to `/runs/<run_id>` on 202, and shows an inline error on 422 or a network failure with the button enabled again.
- [ ] Playwright `monitor.spec.ts` (compose stack, fake runtime, `FAKE_STEP_DELAY_S=0.5`):
  - start from the home-page form → `/runs/<id>` shows `run_started` … `run_completed` and the status `completed`;
  - every row has `receivedAt - createdAt < 1000`;
  - opening `/runs/<id>` for a run started with `POST /runs` shows the same events;
  - no console errors (and so no CORS errors).
- [ ] Existing `home.spec.ts` still passes.
- [ ] CI green: `ruff`, `pyright` strict, `pytest` (existing API tests unchanged), `pnpm lint`, `pnpm format:check`, `pnpm typecheck`, `pnpm test`, OpenAPI/client drift check, compose + Playwright job.

## Manual / demo checks
- [ ] `docker compose up -d --build`, open `http://localhost:3000`, type an input and click "Start sample run". The run page lists events one by one (about 0.5 s apart) and ends with `completed`.
- [ ] Start a run with the README's `curl -s -X POST localhost:8000/runs …` sample, then open `http://localhost:3000/runs/<id>`. The page lists the same events. Reloading the page after the run finishes shows the full list and `completed`.
- [ ] `http://localhost:3000/runs/00000000-0000-0000-0000-000000000000` shows "run not found".
- [ ] Optional: with `AGENTIC_RUNTIME=claude` and a key in `.env`, the page shows `text_delta` rows and a `usage` row.

## Merge criteria
- [ ] All checks above pass in CI.
- [ ] `web/openapi.json` and `web/src/api/schema.d.ts` were regenerated and committed (the drift check is green).
- [ ] README "Monitor" section and `CORS_ORIGINS` documented, and a CHANGELOG entry added.
- [ ] No API key or secret appears in the page, the browser console or the compose logs.
- [ ] Roadmap row 0.8 marked done on the implementation PR (`complete-phase`).
