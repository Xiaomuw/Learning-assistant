# Data, Configuration and Release Audit

**Status: BLOCKED for public release.** This is an evidence and action register, not a completed legal/security audit.

## Verified observations

| Area | Finding | Next action |
| --- | --- | --- |
| 408 practice bank | `data/practice_questions/` contains the canonical `all_408.json` and subject mirrors; an existing test expects 530 questions / 53 concepts. | Identify authors/rightsholders and permission to publicly redistribute all included questions and explanations, or remove/replace unauthorized material. |
| Untracked curriculum | `backend/app/application/notebooks/curriculum_seed.py` loads packages from `backend/storage/data/curriculum/`, under the ignored `backend/storage/` path. | Make fresh-clone tests independent of unpublished data, or supply legally redistributable fixtures. |
| Dev configuration | `docker-compose.yml` publishes Postgres 5434, backend 8003, frontend 3003 and uses a predictable database fallback password. | Restrict host access or bind loopback; never reuse defaults in production. |
| Mini-program | The tracked project config included a specific developer AppID; this PR proposes `touristappid`. | Provide a local AppID via `TARO_APP_ID` / `WECHAT_MINI_APP_ID`, with private configuration ignored. |
| Third-party code and packages | A complete resolved dependency-license/vulnerability and embedded-asset review has not been run. | Audit direct/transitive dependency licenses, advisories, assets and attribution. |
| Known Next.js dependency vulnerability range | `frontend/package.json` pins `next@14.2.29`, a version included in publicly disclosed affected ranges. Actual exploitability depends on deployment/features. | Track [security upgrade #4](https://github.com/Xiaomuw/Learning-assistant/issues/4); upgrade to an actively patched major release with regression checks. |
| Credentials and ownership | A comprehensive historical secret scan and code-contributor ownership review has not been verified. | Audit authorized repository and Git history; revoke any exposed secrets. |

Tracked dataset rights: [issue #5](https://github.com/Xiaomuw/Learning-assistant/issues/5).

## Dataset provenance register (owner-completed)

Record **for each data source and any copied question**:

- Original source identifier, author/rightsholder, and content creation method (independent, AI-assisted, adapted or copied).
- Documentary permission, including rights to publish, adapt and redistribute wording, options and explanations.
- License version, attribution/copyright requirements and any restrictions.
- Evidence reference stored outside the public repository if private.
- Decision: **APPROVED**, **REPLACE**, **REMOVE**, or **REVIEW**.

Excluding a dataset from the repository Apache-2.0 scope does **not** authorize its existing public distribution. If the right to distribute cannot be demonstrated, remove or replace the content in the public tree and plan history remediation where appropriate. History rewriting may break clones, forks and commit links; deletion does not revoke leaked credentials.

## Minimum release gates

- [ ] Audit dataset provenance, upstream ownership and rights of all original/borrowed code and assets.
- [ ] Upgrade Next.js and validate App Router compatibility ([issue #4](https://github.com/Xiaomuw/Learning-assistant/issues/4)).
- [ ] Review licenses and active advisories of resolved direct/transitive dependencies.
- [ ] Scan current tree and Git history for credentials and sensitive data, remediate if discovered.
- [ ] Run a fresh-clone build with independent, redistributable test fixtures.
- [ ] Pass expanded CI plus full backend/unit, isolated Postgres integration, smoke and core UI flow tests.
- [ ] Verify safe development/production configuration with non-default credentials.
- [ ] Publish owner-approved changelog, limitations, source notices and release tag.

See [open-source readiness](OPEN_SOURCE_READINESS.md); a successful static check is not release approval.
