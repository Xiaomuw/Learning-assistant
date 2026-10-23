# Combined candidate verification branch

This branch combines the exact reviewed-proposal heads in
[candidate-inputs.json](audits/candidate-inputs.json) solely to run the full existing
workflow set on one SHA. Main remains unchanged; no PR is automatically merged.
The integration PR is **validation only**, not a request to bypass the individual
reviews or publish a release.

The only composition conflict was THIRD_PARTY.md: retain both #29's dated dependency
inventory disclosure and #39's traceable navigation-source/notices paragraph.
All Action pins, CSS/stream checks, Taro notice checks and full Hooks rules remain.

Additional candidate checks build both production Dockerfiles locally, initialize
an isolated PostgreSQL database through the production Compose migration service,
check health and anonymous proxy rejection, and dump/restore synthetic data into
a second disposable database. They scan exact local image IDs with Trivy 0.76.1,
retain HIGH/CRITICAL findings without suppression, and generate license inventories
and CycloneDX SBOMs. No image is pushed and no online deployment occurs.

License scanner output is evidence for manual distribution review, not a generated
approval or a complete attribution/source-offer bundle. A successful dump/restore
of synthetic data is not proof that an owner's existing production database can
be upgraded or rolled back safely. TLS, physical devices, paid providers, historical
rights and real external adoption remain separate gates.

The source-archive exclusion applies to historical reports only. Test fixtures
are original synthetic data; no old question corpus is reintroduced. Browser
recordings show the actual UI against explicitly synthetic API responses.

**Release remains NO-GO** while vulnerability, ownership and external acceptance
gates are open, even if every application compatibility workflow passes.

The initial APP_ENV=production startup was blocked by missing required production
configuration (including WeChat credentials). No fake provider credentials are
supplied. The disposable packaging/backup smoke therefore explicitly uses
APP_ENV=development with production Dockerfiles/Compose. This does not validate
production startup requirements, TLS or real WeChat login; those remain blocked.
Image scans run after a successful build even if runtime acceptance fails.
