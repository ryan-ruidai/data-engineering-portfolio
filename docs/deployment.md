# Deployment boundaries

The main multi-table project runs with `python3 -m commerce.run`; see [its operating runbook](commerce/runbook.md) for full/replay/late batches, failed-run audit and atomic report publication. The smaller original payment module below has different input data and limitations. Neither is cloud deployed.

## Original payment module

The executable deployment is a local Python 3.9+ batch job with SQLite 3.25+. No third-party packages or credentials are needed. Run from the project root:

```sh
python3 -m unittest discover -s tests -v
python3 -m pipeline.run --db build/payments.db --report build/report.html
python3 -m pipeline.run --db build/payments.db --report build/report.html
```

Open `build/report.html` in a browser. The second run should insert zero and identify 11 duplicates. Use a new database path to demonstrate a clean first run. Never point this demo at private data.

GitHub Actions configuration tests Python 3.9 and 3.12 and runs both modules, including retail base/late replay scenarios. The workflow is implemented; a remote green run is only verified after publication. This project does not configure GitHub Pages or create hosting resources automatically.

## Proposed production/cloud mapping
- Object storage: immutable source objects with checksums and controlled retention.
- Managed SQL warehouse/database: staging and accepted events, constraints, snapshot/mart tables.
- Scheduler: bounded batch retries, unique run IDs, failure alerts; concurrency lock.
- Secrets manager and least-privilege workload identity, not repository credentials.
- Dashboards: quality freshness, rejection ratio, exact payment/order balances.

Before deploying: select region/provider and spending limit, validate data classification/access, benchmark batch size, validate process-kill recovery/alerts and concurrent-writer prevention, test backups/recovery, verify target database integration. The retail module already implements durable handled-failure audit and atomic latest-report pointer publication; these local mechanisms do not constitute cloud operations. None of these cloud resources has been provisioned or tested. This plan is intentionally not a fake deployment badge or untested infrastructure scaffold.
