# Validation: POST /runs + GET /runs/{id}/events (SSE)

## Done when (from roadmap)
> `curl` streams events of a live run

The integration tests below stand in for `curl`. They drive the real API and worker against real Postgres and Redis, and read the raw `text/event-stream` the same way `curl -N` does.

## Automated checks
Integration tests (`@pytest.mark.integration`, Postgres + Redis via Testcontainers, migrations applied):

- [ ] `test_post_run_returns_202`: `POST /runs` with `two-step-sequence.json` returns 202 with `run_id` and `events_url`. The `runs` row exists with status `queued` and the run id is on the Redis queue.
- [ ] `test_post_run_rejects_invalid_spec`: an invalid fixture spec returns 422, with no `runs` row and nothing enqueued.
- [ ] `test_live_stream_end_to_end`: start the worker loop (step delay > 0), POST a run and open the stream **before** the run finishes. The frames arrive while the run is still running, `id`s are 1..N with no gaps or duplicates, the first is `run_started`, the last is `run_completed`, and the stream then closes. `runs.status` = `completed`.
- [ ] `test_stream_finished_run_replays_and_closes`: streaming a completed run returns all stored events and closes without waiting.
- [ ] `test_stream_resumes_from_last_event_id`: reconnect with `Last-Event-ID: k` (and separately `?after=k`). Only events with seq > k arrive, with no duplicates.
- [ ] `test_stream_unknown_run_404`
- [ ] `test_failed_run_streams_run_failed`: a fake script that fails a node makes the stream end with `run_failed`, and the worker keeps taking the next job.
- [ ] `test_sink_notifies_on_insert`: a `LISTEN` connection receives `<run_id>:<seq>` for each emitted event.
- [ ] Existing 0.5 store / migration tests updated and passing (the sink no longer inserts `runs`).

## Manual / demo checks
- None required for merge. The README documents the `curl` demo for reviewers who want to try it.

## Merge criteria
- [ ] All checks above pass in CI, along with the existing ruff, pyright (strict) and pytest jobs.
- [ ] README and CHANGELOG updated. Roadmap phase 0.6 marked done (`complete-phase`).
- [ ] No secrets or connection strings in logs or event payloads.
