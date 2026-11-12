"""Republish a committed report without reading sources or rerunning ingestion."""
import argparse
import json
from pathlib import Path
from .run import connect, export_report


def recover(warehouse, run_id, out):
    """Only recover the newest successful run; never silently roll back latest.json."""
    if not Path(warehouse).is_file():
        raise FileNotFoundError('warehouse_not_found')
    db = connect(warehouse)
    try:
        row = db.execute("SELECT status, report_json FROM ops_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None or row['status'] != 'succeeded' or not row['report_json']:
            raise ValueError('run_has_no_committed_report')
        newest = db.execute("SELECT MAX(run_id) FROM ops_runs WHERE status='succeeded'").fetchone()[0]
        if run_id != newest:
            raise ValueError('refuse_to_publish_older_run')
        report = json.loads(row['report_json'])
        if report['run_id'] != run_id:
            raise ValueError('persisted_report_run_mismatch')
        try:
            export_report(db, report, out)
        except Exception:
            db.execute("UPDATE ops_runs SET export_status='failed' WHERE run_id=?", (run_id,))
            db.commit()
            raise
        return report
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--warehouse', type=Path, required=True)
    parser.add_argument('--run-id', type=int, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    report = recover(args.warehouse, args.run_id, args.out)
    print('Recovered committed report for run ' + str(report['run_id']))


if __name__ == '__main__':
    main()
