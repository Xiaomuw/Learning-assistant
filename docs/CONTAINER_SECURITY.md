# Container reproducibility and vulnerability gate

Checked 2026-10-23 against main `712c0538571d01129c0f8b1fb5488b35c9df6058`.
**Release decision: NO-GO.** Pinning an image does not make it vulnerability-free.

## Fixed inputs

The four existing public image tags now include immutable OCI index digests in
all 15 static references: development/production Dockerfiles, Compose database
services and PostgreSQL CI services. The [inventory](audits/container-digests-2026-10-23.json)
records registry, platforms and affected files. Each digest was checked against
the SHA-256 of the actual registry response bytes, not copied from an example.
Multi-platform indices are retained; runtime testing here is linux/amd64 only.

The PostgreSQL major version and Debian base family are unchanged. Do not treat
this change as permission to attach an existing database volume to a different
OS/major-version image. Back up and rehearse restoration before future changes;
collation libraries, extension versions and on-disk compatibility need separate
review. Application images supplied through BACKEND_IMAGE/FRONTEND_IMAGE remain
owner-provided and must be built/scanned and referenced by their own digests before
deployment. No production data, container registry publication or deployment is
part of this change.

## Actual scan results

Trivy 0.76.1 was downloaded from the official upstream release and its archive
SHA-256 verified. The database timestamp is included in the
[normalized findings](audits/container-findings-2026-10-23.json). Scans use remote
images, linux/amd64, OS and bundled language packages, and HIGH/CRITICAL severity.
Unfixed findings are retained. Counts are package/advisory pairs, not distinct CVEs.

| Image | HIGH | CRITICAL | Distinct advisory IDs | Result |
| --- | ---: | ---: | ---: | --- |
| python:3.12-slim | 44 | 0 | 8 | Blocked |
| python:3.13-slim | 48 | 0 | 12 | Blocked |
| node:22-alpine | 11 | 0 | 10 | Blocked |
| pgvector/pgvector:pg16 | 113 | 16 | 58 | Blocked |

These are scanner matches, not demonstrations of exploitability in the application.
Many OS rows lack a fixed version; some bundled tooling has published fixes.
Review upstream package advisories and actual image reachability, then rebuild and
rescan a compatible image. Do not suppress findings merely to obtain green CI.
The initial Python 3.13 scan warned about third-party SBOM accuracy; the recorded
gate run produced the same counts, which does not independently validate that metadata.
No comprehensive binary, license, secret or application-image clearance is claimed.

## Repeatable checks

Use the checksum-verified Trivy version in `.github/workflows/container-security.yml`,
then run from the repository root with a new output directory:

```bash
python -m unittest discover -s scripts/tests -p 'test_container_scan.py' -v
python scripts/scan_container_bases.py --trivy /path/to/trivy --output-dir /tmp/la-new-container-scan
```

The wrapper exits **0** only when all scans have valid, clean reports, **1** when
HIGH/CRITICAL matches exist, and **2** for scanner/report errors. Trivy itself uses
exit 10 for findings, allowing tool errors to be distinguished. Five synthetic
tests protect missing/malformed reports, inconsistent exit codes and reuse of
stale clean reports. The full script suite passes 17 tests; the real scan exits 1.

The new workflow runs on PRs, manual dispatch and weekly on the default branch
after review/merge. It preserves JSON reports as 14-day artifacts even on failure.
Its security check is expected to remain red while these findings exist. Existing
build/auth/Compose workflows remain necessary compatibility evidence and cannot
override that gate. Final application images, added apt/pip/npm packages and arm64
must be scanned separately on the final candidate; no such acceptance is implied.

## Updating pins

1. Resolve the intended tag from its upstream registry and verify the OCI manifest
   digest against response bytes. Preserve required architectures.
2. Update all corresponding references and the inventory together in a small PR.
3. Scan with a current vulnerability database; keep the timestamp and unsuppressed
   result. Package repository updates during Docker builds remain mutable inputs.
4. Run fresh migrations, authentication, Compose and client container smoke tests.
   Rehearse backup/restore separately when database or OS compatibility changes.
5. Obtain maintainer review. No automatic production image refresh or deployment
   follows from updating this inventory.
