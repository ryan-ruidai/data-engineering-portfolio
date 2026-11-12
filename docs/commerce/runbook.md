# Local operating runbook

## Run and inspect

```sh
python3 -m unittest discover -s tests -v
python3 -m commerce.run
python3 -m commerce.run --batch late
```

For a fresh, separate reproduction without removing any previous data:

```sh
python3 -m commerce.run --workdir build/commerce-verification
```

Inputs are under `<workdir>/inputs`; warehouse is `<workdir>/warehouse.sqlite`; reports are under `<workdir>/reports/run-N`. Inputs are not modified by extraction. Do not point source generation at a real database. Do not overlap runs.

Inspection with Python's sqlite3 or a SQLite client:

```sql
SELECT run_id, started_at, status, export_status, error, metrics_json FROM ops_runs ORDER BY run_id;
SELECT entity, row_number, reason, payload_json FROM raw_event_rows WHERE disposition='rejected';
SELECT * FROM quality_issues ORDER BY run_id;
SELECT * FROM gold_order_reconciliation ORDER BY order_id;
SELECT payment_id, first_run, source_line FROM silver_payment_events ORDER BY event_id;
```

`manifest_json` identifies exact event CSV content and the canonical extracted retail snapshot hash, not source database file layout. `first_run/source_line` joins event lineage back to its raw row. Every committed snapshot raw row has its run/entity/ordinal. Raw rows in a failed transaction roll back; the failed attempt/status/error and available manifests remain in ops_runs. The source files remain available for replay.

## Failure behavior

- Invalid source snapshot or CSV header: fail the entire batch and retain prior silver/gold state.
- Invalid event row: quarantine visibly, continue the batch, issue a quality alert. Latest valid state can therefore be older than the rejected row. Investigate before certifying a report.
- Mid-transaction exception: rollback business and raw writes; record failed run separately. Tests inject a failure after event acceptance and verify both rollback and successful recovery.
- Export error: the database run remains succeeded, export_status becomes failed. Previous latest.json remains unchanged. Persisted report_json allows regenerating the exact committed report without rerunning source ingestion.
- Process termination/power loss: SQLite transaction recovery protects writes, but a previously inserted run may remain `running`; no watchdog claims to repair it. Investigate before starting another writer.

## Recover an export without ingesting again

For the newest successful database run, use the persisted report rather than live views:

```sh
python3 -m commerce.recover --warehouse build/commerce/warehouse.sqlite --run-id N --out build/commerce/reports
```

Replace N with the latest succeeded run ID from `ops_runs`. This command does not read source files, insert a run, or change financial facts. It exports the exact committed JSON and updates only export status. Missing/failed runs and older successful runs are rejected before publication, preventing accidental rollback of the latest pointer. No warehouse is created if the path does not exist. An export failure remains marked failed and can be retried.

Run only when ingestion and other exporters are idle. This is a single-writer local workflow, not distributed locking or disaster recovery. Keep the warehouse and source backups; this command cannot recover lost database data.

## Deployment boundary

CI executes the local engine and smoke scenarios, not a cloud deployment. Production adaptation requires target-store integration tests, concurrency/orchestration, source retention and contract change management, access controls, operational alerts, recovery objectives and measured capacity. Cloud resources, credentials and spend are deliberately absent. See deployment notes for a staged evaluation, not a claim of provisioning.
