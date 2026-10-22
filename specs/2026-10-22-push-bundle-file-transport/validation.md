# Validation: Fix `openPR` "transport 'file' not allowed"

## Done when
> An approved "Generate docs" run pushes the writer's branch and opens a PR on a real `https://github.com/...` repo.

## Automated checks
- [x] `test_bundle_fetch_works_with_an_https_remote` fails on `main` (`transport 'file' not allowed`) and passes on this branch.
- [x] The rest of `packages/github/tests/test_push.py` still passes.
- [x] CI is green (tests, ruff, pyright).

## Manual / demo checks
- [ ] Rerun "Generate docs" on a GitHub repo and approve the `approve` gate. The `publish` node logs `pr_opened` with a PR URL, and the PR exists on GitHub with the `docs/` changes.

## Merge criteria
- [ ] All checks above pass
- [ ] CHANGELOG "Fixed" entry added
- [ ] No token or host temp path in any new error message
