# Engineering roadmap

Implemented: local layered batch ingestion, raw provenance, validation/quarantine, integer cents, replay-safe accepted events, late events, snapshot/order mart, internal balances, HTML/JSON report, 19 tests and CI configuration.

Next engineering increments:
1. Add durable failed-run auditing and atomic report publication.
2. Add a synthetic rejected-record demonstration report and automated report-quality checks.
3. Model a source order dimension and test missing or unknown order references.
4. Validate MySQL schema and DECIMAL behavior in an isolated integration database. Current integration tests use SQLite.
5. Add an independent reconciliation source with a precise matching contract.
6. Benchmark bounded workloads and exercise backup/recovery before considering a cloud deployment.

Cloud deployment, performance validation and production operation are not completed. Technical claims must remain tied to reproducible evidence.
