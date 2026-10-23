# CI action provenance and checkout credentials

Reviewed on 2026-10-23 against main `712c0538571d01129c0f8b1fb5488b35c9df6058`.
This is a scoped hardening change, not release approval or a complete supply-chain audit.

## Immutable action references

All 24 external action calls in the seven workflows use full commit SHAs. The
existing major versions are retained; comments identify their resolved releases.
The GitHub ref API and `git ls-remote --tags` independently returned the following
mapping from the upstream `actions` repositories:

| Action | Resolved release | Commit |
| --- | --- | --- |
| actions/checkout | v4.4.0 (v4) | `11d5960a326750d5838078e36cf38b85af677262` |
| actions/setup-python | v5.6.0 (v5) | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| actions/setup-node | v4.4.0 (v4) | `49933ea5288caeca8642d1e84afbd3f7d6820020` |

Upstream manifests: [checkout](https://github.com/actions/checkout/blob/11d5960a326750d5838078e36cf38b85af677262/action.yml),
[setup-python](https://github.com/actions/setup-python/blob/a26af69be951a213d495a4c3e4e4022e16d87065/action.yml),
[setup-node](https://github.com/actions/setup-node/blob/49933ea5288caeca8642d1e84afbd3f7d6820020/action.yml).
Their action runtime is Node 20; this differs from the Node 22 application runtime
selected by setup-node. Runtime support and future major upgrades need separate
review. A verified SHA prevents tag movement from silently changing the action;
it does not prove the pinned code or its dependencies are vulnerability-free.

## Credential handling

All 13 checkout steps set `persist-credentials: false`. Current jobs only build,
test and inspect Git state; none needs authenticated pushes after checkout. All
workflows retain `permissions: contents: read` and ordinary `pull_request`/`push`
events. No privileged `pull_request_target` or `workflow_run` trigger is added.

Immediately after checkout, each job runs `scripts/check_ci_checkout.py`. It
checks repository-local Git HTTP extra headers, fails on a match or inspection
error, and never prints header values or Git diagnostics. This catches accidental
credential persistence in the current checkout setup; it does not inspect global
config, process environments, SSH agents or all possible credential stores. It is
a regression check, not a sandbox against malicious PR changes to the check itself.

Tests use newly initialized temporary Git repositories and a synthetic header:

```bash
python -m unittest discover -s scripts/tests -p 'test_ci_checkout.py' -v
python -m unittest discover -s scripts/tests -p 'test_*.py' -v
python scripts/check_ci_checkout.py
git diff --check
```

The three new tests cover a clean checkout, redacted rejection of a stored header,
and an inspection error. Local validation passed all 15 script tests. Workflow
syntax/expressions were checked with upstream actionlint 1.7.12; its downloaded
Linux amd64 archive matched the GitHub release asset SHA-256
`8aca8db96f1b94770f1b0d72b6dddcb1ebb8123cb3712530b08cc387b349a3d8`.
The actual runner credential checks and application builds must also pass the
existing hosted workflows; consult the PR checks for the tested commit.

## Maintenance and remaining boundaries

- Keep the existing weekly GitHub Actions Dependabot configuration. Review its
  proposed SHA and version comment against the upstream repository, then run all
  affected workflows. Existing major-upgrade PRs #9–#11 remain independent reviews.
- When adding or updating a workflow, retain full action SHAs, least permissions
  and credential-free checkout unless an explicitly reviewed job needs otherwise.
- Hosted runner labels, Python/Node patch selection, package downloads and Docker
  image tags remain mutable. Image digest pinning and OS-package vulnerability
  scanning are separate open work; this change does not resolve them.
- Existing application dependency findings, historical question rights, asset
  provenance and live-model/browser/staging acceptance remain release blockers.
