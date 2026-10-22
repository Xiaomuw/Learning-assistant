# Third-party Software and Content

This project depends on software maintained by independent authors, including packages from `backend/requirements.txt`, `frontend/package.json`, and `frontend-weapp/package.json`.

Third-party dependencies, vendored code and assets retain their own license terms. The project's [Apache-2.0](LICENSE) text does **not** relicense external content. Consult the relevant package distributions and upstream notices.

## License review status

An initial resolved dependency/SBOM/license inventory was produced on 2026-10-22; see the [dependency and source review](docs/DEPENDENCY_SECURITY_REVIEW.md) and [sanitized evidence](docs/audits/dependency-review-2026-10-22.json). It includes transitive dependencies and identifies MPL/LGPL/attribution obligations for review. Package metadata does not establish distribution compliance. Embedded image provenance, copied-code ownership and the final distribution-specific notice/source bundle remain incomplete. This page is not a compliance certification.

Before creating a public release package:

1. Generate a dependency and license inventory from the actual lockfiles/build outputs.
2. Review dependency version restrictions and incompatible or copyleft obligations.
3. Check copied source files, assets and screenshots for their original authors and licenses.
4. Preserve any upstream `LICENSE`, `NOTICE`, copyright notices, modification notices and attribution requirements.
5. Resolve the separate 408 dataset provenance issue documented in [data/practice_questions/README.md](data/practice_questions/README.md).

Do not insert guessed upstream license information into notices.
