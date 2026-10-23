# Open-source standards assessment — 2026-10-23

**Decision: suitable for continued public development; not cleared for the first
release. P0 and P2 are not all closed.** This is an evidence-based maintenance
assessment, not legal certification, OSI endorsement or program acceptance.

Baseline main: `712c0538571d01129c0f8b1fb5488b35c9df6058`. Draft proposals are
separate from main. No PR has been merged by this task.

## Criteria and findings

The [OSI Open Source Definition](https://opensource.org/osd) addresses distribution
rights, available source, modifications and nondiscrimination. It does not require
a star count, a vulnerability-free build or a production deployment. The project's
[Apache-2.0 license](https://www.apache.org/licenses/LICENSE-2.0) is OSI approved;
its grant depends on authority to license the material, and redistribution must
preserve applicable license, copyright and attribution notices. A root LICENSE
cannot supply missing rights to copied questions or assets. Sources checked on
2026-10-23.

| Area | Assessment | Evidence / remaining gate |
| --- | --- | --- |
| Open-source license choice | Appropriate for authorized original code | Apache-2.0 and explicit scope exist; original-code/contributor ownership still needs confirmation |
| Public source and contribution process | Foundation present | Both READMEs, CONTRIBUTING, SECURITY, governance, issue/PR templates and CI exist |
| Question-data rights | Not cleared | Current corpus removed and original synthetic examples supplied; historical 530-question rights/exposure remain unresolved |
| Current navigation assets | Scoped replacement proposed | #39 replaces 16 PNG files with four fixed-commit Lucide sources, full ISC/MIT notices and hash/build checks; old Git assets and other media are not cleared |
| Reproducibility | Partially verified | Disposable PostgreSQL, migration, Compose and client CI exist; Python transitives and apt dependencies are not fully frozen; combined candidate must be retested |
| Business behavior | Scoped automated evidence | #30/#33/#34 add real DB/HTTP regressions with controlled models/embeddings; external-provider quality and browser/device acceptance remain open |
| Supply-chain safety | Partial mitigation; NO-GO | #31–#37 propose fixes and Action pins; #38 pins four image digests but its real HIGH/CRITICAL gate fails |
| Distribution obligations | Incomplete | Full built-image/bundle license notices and applicable source obligations require review; source metadata alone is insufficient |
| Maintainer-program evidence | Early-stage | Real code, tests and reviewable maintenance exist; verified external reuse/adoption is absent and must not be invented |

## Remaining work by priority

P0 release blockers:

1. Review the pending fixes, reconcile overlaps and run every required workflow on
   one final candidate SHA. Individual PR results do not establish combined safety.
2. Triage and remediate unresolved JavaScript and container advisories. #38's four
   linux/amd64 scans report HIGH/CRITICAL package-advisory pairs of 44/0, 48/0,
   11/0 and 113/16 respectively. These are scanner matches, not proven exploits.
   Preserve failing gates; scan final application images too. Do not change the
   database OS family or assume existing volumes survive without backup/restore
   and compatibility testing.
3. Owner must establish original-code rights, decide historical corpus remediation
   based on rights evidence, and confirm historical test credentials were never
   reused. No history rewrite or credential disclosure is authorized here.
4. Complete distribution license/source obligations and isolated live-model,
   browser/device and staging acceptance. Provider tests require a separately
   approved budget and sandbox resources; no credentials belong in an issue/chat.

P1 quality work: resolve Hooks warnings (#8), exercise optional integrations,
verify browser accessibility and errors, and tighten reproducible dependency
resolution without speculative major upgrades.

P2 sustainable maintenance: review #39 and remaining asset provenance, capture
real accepted demos, document actual external feedback, and review dependency
updates periodically. These are continuing tasks; lack of stars is not an OSD
failure. Asset distribution rights remain a P0 gate wherever unresolved material
would ship, even if asset cleanup was originally grouped under P2.

## Reassessment and owner-dependent evidence

The owner can resolve factual rights questions with authorship/contributor records
and original source/license evidence. If evidence is unavailable, decide on
replacement/exclusion and a separately reviewed historical-remediation plan; do
not invent licenses. Live acceptance needs an owner-provided disposable target,
test accounts and explicit paid-service authorization. No production service is
required for the automated tests already present.

Reassess after those gates close, recording the exact main/candidate SHA, full
workflow links, refreshed advisory database and packaged license notices. Then
distinguish three conclusions: license/distribution compliance, this project's
release readiness, and the external program's independent admission decision.
See [verification](RELEASE_VERIFICATION.md), [security review](DEPENDENCY_SECURITY_REVIEW.md)
and [release runbook](RELEASE_CANDIDATE.md). **Current release decision: NO-GO.**
