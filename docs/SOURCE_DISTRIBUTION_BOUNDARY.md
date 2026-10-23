# Source distribution boundary

The root `.gitattributes` excludes `docs/test-reports` from `git archive` output.
The directory includes 17 historical UI screenshots and old test reports whose
image rights and personal-data/credential review are incomplete. They are not
fresh acceptance evidence. Code and applicable license/notice files remain in
the archive. No Git objects, branches, repository visibility or history are changed.

Use a reviewed candidate SHA, not an unreviewed moving branch:

```bash
git archive --format=tar --output=/tmp/learning-assistant-source.tar <reviewed-sha>
tar -tf /tmp/learning-assistant-source.tar
python -m unittest discover -s scripts/tests -p test_source_archive.py -v
```

This rule does not apply to a clone, a manually copied working directory or a
custom packager that ignores Git attributes. Verify any actual GitHub archive or
release package separately before distribution. No archive is published by CI.

The dated asset inventory records paths and Git blob identifiers only. At its
baseline, the 16 navigation PNGs have no established provenance; Draft #39 proposes
traceable replacements and full ISC/MIT notices. After that change, use its SVG/PNG
manifest for current assets. Replacement does not clear historical PNG rights.

Original-code/contributor authority, historical 530-question rights, dependency
source/notice obligations and remaining media still require evidence. The owner
has not supplied an authorship attestation in this task. Exclusion from an archive
is exposure reduction, not a legal determination or a complete release clearance.

## Project license in built distributions

Both Docker build contexts and the Taro project carry byte-identical copies of
the root LICENSE and LICENSE-SCOPE.md. Production frontend explicitly copies them
to /app; backend COPY includes them. Taro copies both into dist, with CI comparing
the output bytes. These copies must change together with the root files. They do
not replace dependency-specific notices or license texts and do not assert rights
the maintainers have not established. Final WeChat upload retention still needs
physical-device/package acceptance.
