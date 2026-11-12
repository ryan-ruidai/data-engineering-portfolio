import csv
import tempfile
import unittest
from pathlib import Path
from pipeline.run import FIELDS, connect, ingest, metrics, report, validate

ROOT=Path(__file__).resolve().parents[1]
class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db=connect(':memory:')
        self.addCleanup(self.db.close)
        ingest(self.db,ROOT/'data/synthetic/payment_events.csv')
    def batch(self,rows):
        p=Path(self.temp.name)/'batch.csv'
        with p.open('w',newline='') as f:
            w=csv.writer(f);w.writerow(FIELDS);w.writerows(rows)
        return ingest(self.db,p)
    def test_replay_is_business_idempotent(self):
        before=metrics(self.db)
        result=ingest(self.db,ROOT/'data/synthetic/payment_events.csv')
        self.assertEqual(result['inserted_count'],0)
        self.assertEqual(result['duplicate_count'],11)
        self.assertEqual(metrics(self.db),before)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM raw_rows').fetchone()[0],11)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM runs').fetchone()[0],2)
    def test_late_old_event_does_not_rewind_snapshot(self):
        self.batch([[200,'P100',501,'999.00','pending','2026-11-09 00:00:00']])
        self.assertEqual(metrics(self.db)['successful_snapshot_cents'],24500)
    def test_late_new_state_updates_snapshot(self):
        self.batch([[201,'P100',501,'80.00','voided','2026-11-11 00:00:00']])
        self.assertEqual(metrics(self.db)['successful_snapshot_cents'],16500)
    def test_quarantine_and_conflicting_ids(self):
        r=self.batch([[101,'P100',501,'9.00','pending','2026-11-10 09:00:00'],[202,'P200',500,'-1','succeeded','2026-11-10 09:00:00'],[203,'P200',500,'1.00','INVALID','2026-11-10 09:00:00']])
        self.assertEqual(r['rejected_count'],3)
        self.assertEqual(metrics(self.db)['clean_events'],11)
        self.assertEqual(metrics(self.db)['rejected_rows'],3)
    def test_bad_contract(self):
        valid=dict(zip(FIELDS,['202','P200','500','1.00','succeeded','2026-11-10 09:00:00']))
        for key,bad in [('amount','NaN'),('amount','1.001'),('payment_id',''),('event_id','0'),('updated_at','2026-02-30 09:00:00')]:
            with self.subTest(key=key,bad=bad),self.assertRaises(ValueError):validate(dict(valid,**{key:bad}))
    def test_cents_are_exact(self):
        self.batch([[202,'A',600,'0.10','succeeded','2026-11-10 09:00:00'],[203,'B',600,'0.20','succeeded','2026-11-10 09:00:00']])
        self.assertEqual(self.db.execute('SELECT amount_cents FROM order_snapshot WHERE order_id=600').fetchone()[0],30)
    def test_infrastructure_failure_rolls_back_whole_batch(self):
        import sqlite3
        counts=lambda: tuple(self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('runs','raw_rows','clean_events','rejected_rows'))
        before=counts()
        self.db.execute("CREATE TRIGGER fail_event BEFORE INSERT ON clean_events WHEN NEW.event_id=999 BEGIN SELECT RAISE(ABORT,'injected failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.batch([[998,'NEW1',700,'1.00','succeeded','2026-11-10 09:00:00'],[999,'NEW2',701,'2.00','succeeded','2026-11-10 09:00:00']])
        self.assertEqual(counts(),before)
        self.assertEqual(metrics(self.db)['successful_snapshot_cents'],24500)
    def test_report_consistent(self):
        p=Path(self.temp.name)/'report.html'
        m=report(self.db,p)
        self.assertTrue(all(m['checks'].values()))
        self.assertEqual(m['successful_snapshot_cents'],24500)
        self.assertIn('245.00',p.read_text())
        self.assertTrue(p.with_suffix('.json').exists())
    def test_newer_void_then_replay_stays_void(self):
        self.batch([[250,'P100',501,'80.00','voided','2026-11-11 00:00:00']])
        ingest(self.db,ROOT/'data/synthetic/payment_events.csv')
        self.assertEqual(metrics(self.db)['successful_snapshot_cents'],16500)
if __name__=='__main__':unittest.main()
