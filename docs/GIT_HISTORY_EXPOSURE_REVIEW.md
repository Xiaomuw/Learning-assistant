# Historic Git Exposure — decision record (not a remediation execution)

**Review state: NOT RESOLVED.** This document inventories likely exposure and presents choices; it does not rewrite repository history or delete any private data.

## What can be verified

- The original [`main` tree](https://github.com/Xiaomuw/Learning-assistant/tree/main/data/practice_questions) had five publicly committed JSON files containing a 530-question corpus gathered using AI-assisted web searches of existing third-party question banks.
- The owner has confirmed the collection method. The individual upstream rights, licenses and redistribution permissions have not been established.
- [Draft PR #6](https://github.com/Xiaomuw/Learning-assistant/pull/6) removes those five files from the proposed **current** tree and protects local imports; until a deliberate merge, `main` is unchanged.
- [Draft PR #3](https://github.com/Xiaomuw/Learning-assistant/pull/3) documents Apache-2.0's limited scope and retains an **ID-only** historical review ledger. No question wording is copied into that ledger.
- Earlier commit objects, branch histories, referenced pull requests, forks, clones and third-party caches are **not** automatically erased by a normal deletion commit. Full inventory of all copies has **not** been established.

## Public branch inventory — checked 2026-10-21

This is a **current-file-tree listing**, not a complete Git history scan or legal-content review. The authenticated GitHub repository API returned eight active branches; the following counts are for JSON files directly in `data/practice_questions/` at each branch head:

| Branch | JSON files in that directory | Notes |
| --- | ---: | --- |
| `main` | **5** | Original canonical file + four subject mirrors still publicly in the default branch |
| `codex/docker-production-deploy` | **5** | Older active PR/deployment branch retains the five JSONs |
| `codex/qa-408-flow-web-toggle` | **5** | Older topic branch retains the five JSONs |
| `mian` | **42** | Contains `all_408_v2.json`, a cleanup-report JSON and many `batch_*.json`; individual contents and licensing **not reviewed** |
| `chore/separate-unverified-question-bank-2026-10` | **0** | Draft PR #6 proposed data-free tree |
| `chore/oss-readiness-2026-10` | **0** | Stacked Draft PR #3 current tree |
| `codex-release-2026-05-08` | No such directory at branch head | **Not** proof of clean prior history |
| `codex-release-main-2026-05-08` | No such directory at branch head | **Not** proof of clean prior history |

Across the 42 `mian` JSON objects, GitHub reports approximately **2.2 MB** of files. The count includes supporting JSON reports and **does not mean there are 42 independently copyrighted question banks**. No blanket conclusion about their provenance or redistribution rights has been made.

GitHub repository metadata showed **0 recorded forks** and the releases API returned **no published Releases** at the time checked. These observations **cannot** establish that third-party clones, downloaded ZIPs, cached copies or older commits do not exist. Tag enumeration was not verified.

### Impact on remediation

**Merging PR #6 to `main` will not clean `codex/docker-production-deploy`, `codex/qa-408-flow-web-toggle`, or `mian`.** Before declaring public cleanup complete, determine whether those branches are still needed and how to remove or replace the unreviewed files without losing legitimate development work. Do **not** delete these branches automatically. Any coordinated history rewrite remains a separate high-impact decision.

## Practical options (maintainer decision, not action)

| Route | Result | Limitation / risk |
| --- | --- | --- |
| **A. Merge ordinary deletion first (recommended immediate review path)** | The default source tree stops shipping the five JSON files and future source archives omit them | Old Git commit history and copies may still expose them |
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

**No force-push, history rewrite, visibility change, repository deletion or GitHub Support ticket has been performed by these draft PRs.**
