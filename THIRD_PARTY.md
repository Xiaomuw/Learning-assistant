# Third-party Software and Content

This project depends on software maintained by independent authors, including packages from `backend/requirements.txt`, `frontend/package.json`, and `frontend-weapp/package.json`.

Third-party dependencies, vendored code and assets retain their own license terms. The project's [Apache-2.0](LICENSE) text does **not** relicense external content. Consult the relevant package distributions and upstream notices.

## License review status

The current navigation PNG assets in both clients are generated from reviewed
Lucide 0.475.0 SVGs (ISC, with Feather MIT portions). Their exact upstream commit,
editable sources, licenses, modifications and file hashes are in
[third_party/navigation-icons](third_party/navigation-icons/README.md). Each
client includes the complete attribution/license texts in its icon NOTICE.txt;
Taro copies that notice into its build output. This replacement does not clear
the rights of old PNG blobs retained in Git history or other unreviewed assets.

A complete inventory of direct **and transitive** dependency licenses, embedded icons/images, vendored sources, copied code, and their applicable attribution requirements has **not** yet been completed. This page is a disclosure of work to do, not a compliance certification.

Before creating a public release package:

1. Generate a dependency and license inventory from the actual lockfiles/build outputs.
2. Review dependency version restrictions and incompatible or copyleft obligations.
3. Check copied source files, assets and screenshots for their original authors and licenses.
4. Preserve any upstream `LICENSE`, `NOTICE`, copyright notices, modification notices and attribution requirements.
5. Resolve the separate 408 dataset provenance issue documented in [data/practice_questions/README.md](data/practice_questions/README.md).

Do not insert guessed upstream license information into notices.
