# Plan: Fix `openPR` "transport 'file' not allowed"

## 1. Regression test (red)
- [x] In `packages/github/tests/test_push.py`, add `test_bundle_fetch_works_with_an_https_remote`: build a `_Git` for an `https://github.com/...` remote, seed its repo with the base commit using host git, then fetch the writer's bundle through `_Git`. No network is used.
- [x] Run it on the unfixed code and confirm it fails with `transport 'file' not allowed`.

## 2. Fix (green)
- [x] In `packages/github/src/agentic_github/push.py`, add `_Git.fetch_bundle(bundle, ref)`. It runs `git fetch` with `-c protocol.file.allow=always` added for that command only.
- [x] `push_bundle` calls `fetch_bundle` instead of `run("fetch", <bundle>, ...)`.
- [x] Keep `protocol.file.allow` for the remote only when the remote is `file://` (tests).

## 3. Changelog
- [x] Add a `### Fixed` entry under `[Unreleased]` in `CHANGELOG.md`.
