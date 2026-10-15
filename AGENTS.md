# Hydrology contributor guidance

Preserve native temporal basis, provider flags, missingness, and provenance. Do not
relabel provider daily values as UTC or sum nested gauges/distributaries. Keep this
package independently installable. Sibling repositories are read-only dependencies.
Read README.md and docs/CONTRACTS.md before product changes; docs/SOURCES.md before
source changes. Use explicit training-only climatologies and fail closed on source
ambiguity. Never commit cache/backfill data or credentials.

Run `.venv/bin/python -m pytest -q` and `git diff --check` after behavioral changes.
Default tests are offline synthetic fixtures. Network validation is explicit:
`.venv/bin/python scripts/validate_pilot.py`. Record actual live coverage separately.
Do not push, merge, overwrite released artifacts, or initiate a multi-decade download
as a test. See docs/VALIDATION.md for this implementation's measured acceptance gaps.

Final H3 products follow `final/static.parquet` (H3 × metric),
`final/dynamic.parquet` (H3 × UTC date × metric), and `final/catalog.json`.
Delete only build-owned HTTP downloads, and only after validating final files,
catalog and saved release. Preserve failed-build downloads for resumption and never
sweep shared caches or user-provided input files. Tests must cover cleanup boundaries.
