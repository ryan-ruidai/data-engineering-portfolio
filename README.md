# Payment snapshot data pipeline

**A runnable data-engineering portfolio using synthetic data. Not production experience, an official interview problem, or an accounting system.**

## What an interviewer can inspect
A complete small local batch path: raw ingestion → validation/quarantine → accepted events → latest payment states → order-level mart → reconciliation checks → HTML report. It includes replay-safe ingestion, late event handling, lineage, tests and a CI workflow. It does not claim enterprise-scale deployment.

[Architecture and contracts](docs/architecture.md) · [Deployment boundary](docs/deployment.md) · [Sample report HTML](reports/demo.html) · [Machine-readable sample](reports/demo.json)

Download/open `reports/demo.html` to view the sample; GitHub source pages do not render HTML as a website. Generate your own with the commands below.

## Run in three commands
Requires Python 3.9+ and SQLite 3.25+. No dependencies, account, secret, cloud resource or existing database required. Run from the project root:

```sh
python3 -m unittest discover -s tests -v
python3 -m pipeline.run
python3 -m pipeline.run
```

Open `build/report.html`. First run inserts 11 events. Replay inserts 0 and records 11 duplicates; business state is unchanged. Each completed batch is logged; failed transactions roll back and exit nonzero without a durable run record. Inputs stay untouched; generated SQLite/output files live under ignored `build/`.

Expected base fixture: **11 events → 7 latest payments → 5 successful payments → 4 orders**, **CAD 245.00 current successful payment snapshot amount**. This is **not revenue, profit or cash settlement**. Orders 501/503/505/506 have 80.00/75.00/90.00/0.00 respectively.

## Correctness that matters
- Select latest state across **all** statuses before filtering succeeded. A later voided state must remove an earlier success.
- Latest is UTC `updated_at DESC, event_id DESC`; ID tie-break is an exercise contract.
- Partition by payment, aggregate by order; retain zero amounts and multiple payments per order.
- Exact integer cents in the operational pipeline. No floating-point monetary aggregation.
- Validate before accepting; keep malformed/conflicting records with reasons and source lineage.
- Late older events remain history; late newer events update the snapshot. No arrival-time watermark loses them.

## Verified boundaries
Local 19-test suite passes on Python 3.9 / SQLite. Tests cover expected rows, ties, amount corrections, zero values, early-filter negative control, replay, late states, invalid records and exact cents. The checked-in GitHub Actions workflow is not a claim of a completed remote CI run.

`sql/` preserves the MySQL-oriented SQL reference. Its logic tests run in isolated SQLite; **whole-project MySQL integration and MySQL DECIMAL/constraint behavior remain unverified**. The Python ETL is SQLite-only.

## Layout
- `pipeline/`: executable ingestion, validation, marts, report generator
- `data/synthetic/`: original synthetic input
- `sql/`: reference SQL solution and view refactor
- `tests/`: isolated logic and ingestion tests
- `reports/`: generated synthetic example (not personal runtime state)
- `.github/workflows/ci.yml`: automated checks
- `docs/`: architecture, limitations, interviewer guide and verification roadmap

## Honest scope
Single-machine batch prototype; no benchmark, cloud deployment, source order dimension, independent bank reconciliation, refunds or multicurrency. First accepted conflicting event wins and is flagged for investigation. Failure transactions roll back and exit nonzero but need external failure monitoring. Review [operating limitations](docs/architecture.md) before adapting this to a real system.

