# Historic Git Exposure — decision record (not a remediation execution)

**Review state: PARTIALLY MITIGATED, NOT RESOLVED (checked 2026-10-22).** PRs #6, #3 and #7 are merged into main. The five original question JSONs are absent from the current default tree, but historical commits still contain unreviewed question-bank material; all 30 remote branch heads in the initial inventory were clear in the affected directory. This document records evidence and options; it does not rewrite history or delete private data.

## What can be verified

- The pre-remediation main tree had five publicly committed JSON files containing a 530-question corpus gathered using AI-assisted web searches of existing third-party question banks. [PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) removed their current versions from main in merge commit a0dc819e8d4ff9db481ac8877b67105570829b8c; the current directory retains only its README. Earlier commit objects remain.
- The owner has confirmed the collection method. The individual upstream rights, licenses and redistribution permissions have not been established.
- [PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) is merged. It removes the five JSON files from the current main tree and preserves generic import and AI-practice logic. It does not remove historical commits or other branch copies.
- [PR #3](https://github.com/Xiaomuw/Learning-assistant/pull/3) is merged. Main now has Apache-2.0 and its scope statement, while the ID-only 530-record ledger remains historical review metadata; it contains no question wording and grants no rights to the original content.
- Earlier commit objects, branch histories, referenced pull requests, forks, clones and third-party caches are **not** automatically erased by a normal deletion commit. Full inventory of all copies has **not** been established.

## Public branch inventory — checked 2026-10-22

This is a current-file-tree listing, not a complete Git history scan or legal-content review. The initial full clone had 30 remote branch heads at the time of review (before the new test/security branches). After PRs #23–#25 merged, all checked current branch heads have **zero JSON files** under data/practice_questions/.

| Branch / group | JSON files in current directory | Notes |
| --- | ---: | --- |
| main | **0** | PR #6 removed the five original question-bank files; README remains |
| codex/docker-production-deploy | **0** | PR #24 merged; branch directory no longer contains question JSON |
| codex/qa-408-flow-web-toggle | **0** | PR #25 merged; only README remains |
| mian | **0** | PR #23 merged; the previous 42 JSON files were removed from the current branch head |
| chore/separate-unverified-question-bank-2026-10 | **0** | Branch used for merged PR #6 |
| chore/oss-readiness-2026-10 | **0** | Branch used for merged PR #3 |
| chore/security-next16-upgrade-2026-10 | **0** | Branch used for merged PR #7 |
| cleanup/* branches | **0** | Branches used to prepare PRs #23–#25; their current trees have no question JSON |
| codex-release-2026-05-08 and codex-release-main-2026-05-08 | No such directory at branch head | Not proof of clean prior history |
| Dependabot, docs and migration-fix branches | **0** | Current branch trees checked; no question JSON found |

Before cleanup, mian contained 42 JSON files (approximately 2.2 MB according to GitHub metadata), including all_408_v2.json, batch files and a cleanup report containing deleted question records. The two older codex branches each had five question-bank JSON files. PRs #23, #24 and #25 removed these files from their current branch heads.

GitHub repository metadata previously showed 0 recorded forks and no published Releases at the time checked. These observations cannot establish that third-party clones, downloaded ZIPs, cached copies or older commits do not exist. A read-only reachable-object inventory was completed in this task; its scope and exclusions are recorded below. It is not a rights clearance or proof that external copies do not exist.

### Read-only reachable history inventory

Baseline `712c0538571d01129c0f8b1fb5488b35c9df6058`, full-clone local refs at review time: 162 commits and 1,718 unique blobs. The count includes locally prepared test commits and the fetched PR #29 branch, not just main ancestry. `git rev-list --objects --all` and `git cat-file --batch` were used without changing Git objects. All 30 initial `refs/remotes/origin/*` branch heads (excluding the symbolic HEAD) had zero JSON files under `data/practice_questions/`; no tags or Releases were present.

The reachable object set still contains **42 distinct JSON blobs under the historical question-bank path, totaling 2,202,071 bytes**. This is a blob/file inventory, not a count of unique questions or an ownership finding. It includes historical batch/combined files; the old 530-question ledger is still unresolved. Neither old JSON text nor question wording was copied into this report or a new commit.

Text secret scanning used detect-secrets 1.5.0 in memory without network credential verification. Binary blobs (91) were inventoried but not OCR/text-scanned. The [security review](DEPENDENCY_SECURITY_REVIEW.md) records candidate counts, false-positive limits and owner confirmation needs. No confirmed live-provider credential is asserted and no clean-history certification is given.

Excluded: GitHub PR-only refs not fetched as branches, unreachable server objects, deleted branches not present in the clone, GitHub caches, external mirrors/clones, and image-content inspection. Broader access/inventory and maintainer decisions are required to resolve those boundaries. All changes in this task are ordinary fast-forward branch updates; there was no force push, history rewrite, branch deletion or repository visibility change.

### Impact on remediation

**All currently checked branch heads are clear of question-bank JSON files, but historical Git exposure remains unresolved.** PRs #23–#25 only delete current files from the relevant branch heads; they do not rewrite older commits or remove copies held by other people. Do not delete branches automatically. Any coordinated history rewrite remains a separate high-impact decision.

## Practical options (maintainer decision, not action)

| Route | Result | Limitation / risk |
| --- | --- | --- |
| **A. Retain completed current-tree deletion** | Already completed by #6/#23–#25; current source archives omit the affected files | Old Git commit history and copies may still expose them |
| **B. Later coordinate history rewrite** | May remove references from the rewritten repository if done comprehensively | Rewrites SHAs, can invalidate signatures and open PR review links, and cannot unilaterally alter third-party forks/clones or guarantees of cached erasure |
| **C. Start a separately created clean repository** | New distribution with only reviewed source can avoid importing the old commit chain | Old repo/links/copies still need independent handling; adoption, links and issue history may be fragmented |

GitHub's [official guidance on removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) documents the technical limitations and side effects of a repository history rewrite. **It primarily addresses sensitive-data cases, not a promise that GitHub Support will remove ordinary copyright-unclear question text or other non-sensitive content.**

## Review checklist before any disruptive history operation

- [ ] Inventory all current branches, tags, releases, PR refs, forks, collaborators and mirror deployments, and list every historical path under which the affected question content appeared.
- [ ] Establish whether there are actually licensed third-party excerpts requiring removal, permission, attribution or other specific remedies. Use suitable legal advice when warranted.
- [ ] Confirm a private, access-controlled preservation/backup plan where legally appropriate (never upload the original questions in a public PR or chat).
- [ ] Notify any collaborators and plan how old clones will avoid reintroducing removed content; expect old PR comments/reviews to be invalidated.
- [ ] Review GitHub's current `git-filter-repo` procedures and limitations. Do not assume a forced push removes cached content or external forks.
- [ ] Obtain a separate deliberate owner decision on changing history, repo visibility or the legacy repository's fate.
- [ ] After any authorized change, verify branch/tag refs and historical accessibility, and update publicly stated limitations honestly.

**No force-push, history rewrite, visibility change, repository deletion or GitHub Support ticket was performed in this review.** Current-tree cleanup is not historical erasure.
