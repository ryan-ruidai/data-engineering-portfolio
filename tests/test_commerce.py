import csv
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from commerce.fixtures import create_sources,write_csv,PAY_FIELDS,REF_FIELDS
from commerce.run import run,snapshot

class CommerceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.source=create_sources(self.root/'inputs'); self.db=self.root/'warehouse.sqlite'
    def tearDown(self): self.temp.cleanup()
    def execute(self,late=False,**kwargs):
        suffix='_late' if late else ''
        return run(self.db,self.source,self.source.parent/('payments'+suffix+'.csv'),self.source.parent/('refunds'+suffix+'.csv'),**kwargs)
    def sql(self,query,args=()):
        with sqlite3.connect(str(self.db)) as db: return db.execute(query,args).fetchall()
    def add(self,entity,rows):
        path=self.source.parent/(entity+'s.csv')
        with path.open('a',newline='') as f: csv.writer(f).writerows(rows)
    def change_source(self,query):
        with sqlite3.connect(str(self.source)) as db: db.execute(query)
    def test_golden_totals_and_order_grain(self):
        r=self.execute(); self.assertEqual(len(r['orders']),6)
        self.assertEqual(r['totals'],dict(original_order_total_cents=32000,collectible_cents=29000,captured_cents=27000,refunded_cents=1000,net_payment_cents=26000,capture_variance_cents=-2000))
        self.assertEqual(r['orders'][0]['captured_cents'],10000)
        self.assertEqual(r['orders'][0]['line_count'],2)
        self.assertTrue(all(r['checks'].values()))
    def test_replay_and_durable_audit(self):
        a=self.execute(); b=self.execute()
        self.assertEqual(a['orders'],b['orders']); self.assertEqual(b['batch_metrics']['payment']['duplicates'],9)
        self.assertEqual(self.sql('SELECT status FROM ops_runs'),[('succeeded',),('succeeded',)])
    def test_delta_and_late_replay(self):
        self.execute(); b=self.execute(late=True); c=self.execute(late=True)
        self.assertEqual(b['totals']['captured_cents'],29000)
        self.assertEqual(b['totals']['refunded_cents'],3000)
        self.assertEqual(b['totals']['net_payment_cents'],26000)
        self.assertEqual(b['quality_issues'],[]); self.assertEqual(b['orders'],c['orders'])
    def test_older_event_cannot_replace_latest(self):
        self.execute(); self.execute(late=True)
        self.assertEqual(self.sql("SELECT event_id,status FROM silver_current_payments WHERE payment_id='P3'"),[(4,'succeeded')])
    def test_latest_status_before_success_filter(self):
        r=self.execute(); cancelled=r['orders'][3]
        self.assertEqual(cancelled['captured_cents'],0); self.assertEqual(cancelled['collectible_cents'],0)
    def test_zero_payment_retained(self):
        r=self.execute(); self.assertEqual(r['orders'][4]['payment_count'],1); self.assertEqual(r['orders'][4]['captured_cents'],0)
    def test_equal_time_tiebreak(self):
        self.add('payment',[(20,'P7',506,6000,'CAD','succeeded','2026-11-10 10:08:00')])
        self.assertEqual(self.execute()['orders'][5]['captured_cents'],6000)
    def test_conflict_quarantined_immutable_original(self):
        self.execute(); self.add('payment',[(9,'P7',506,9900,'CAD','succeeded','2026-11-10 10:08:00')])
        r=self.execute(); self.assertEqual(r['batch_metrics']['payment']['rejected'],1)
        self.assertEqual(r['orders'][5]['captured_cents'],7000)
        self.assertEqual(self.sql("SELECT reason FROM raw_event_rows WHERE disposition='rejected'"),[('immutable_event_conflict',)])
    def test_same_payload_duplicate_in_one_batch(self):
        self.add('payment',[(9,'P7',506,7000,'CAD','succeeded','2026-11-10 10:08:00')])
        self.assertEqual(self.execute()['batch_metrics']['payment']['duplicates'],1)
    def test_parent_reassignment_rejected(self):
        self.add('payment',[(20,'P7',501,7000,'CAD','succeeded','2026-11-11 10:08:00')])
        self.assertEqual(self.execute()['batch_metrics']['payment']['rejected'],1)
    def test_invalid_events_quarantined(self):
        self.add('payment',[(20,'BAD',501,-100,'CAD','succeeded','2026-11-10 10:08:00'),(21,'BAD2',501,100,'USD','succeeded','2026-11-10 10:08:00'),(22,'BAD3',501,100,'CAD','unknown','2026-11-10 10:08:00'),(23,'BAD4',501,100,'CAD','succeeded','invalid')])
        r=self.execute(); self.assertEqual(r['batch_metrics']['payment']['rejected'],4)
        self.assertEqual(r['totals']['captured_cents'],27000)
    def test_unknown_parent_retry(self):
        self.add('payment',[(20,'PNEW',507,100,'CAD','succeeded','2026-11-10 10:08:00')])
        self.assertEqual(self.execute()['batch_metrics']['payment']['rejected'],1)
        self.change_source("INSERT INTO orders VALUES(507,1,'2026-11-10 09:00:00','fulfilled','CAD',0,0)")
        self.change_source('INSERT INTO order_items VALUES(9,507,1,1,100,0)')
        r=self.execute(); self.assertEqual(r['batch_metrics']['payment']['accepted'],1)
        self.assertEqual(r['orders'][-1]['captured_cents'],100)
    def test_multiple_partial_refunds_no_join_fanout(self):
        self.add('refund',[(3,'R2','P1',500,'CAD','succeeded','2026-11-10 12:00:00'),(4,'R3','P2',500,'CAD','succeeded','2026-11-10 12:00:00')])
        r=self.execute()['orders'][0]
        self.assertEqual((r['collectible_cents'],r['captured_cents'],r['refunded_cents'],r['net_payment_cents']),(10000,10000,2000,8000))
    def test_failed_latest_refund_not_deducted(self):
        self.add('refund',[(3,'R1','P1',1000,'CAD','failed','2026-11-10 12:00:00')])
        self.assertEqual(self.execute()['totals']['refunded_cents'],0)
    def test_over_refund_is_visible_not_clamped(self):
        self.add('refund',[(3,'R2','P1',7000,'CAD','succeeded','2026-11-10 12:00:00')])
        r=self.execute(); self.assertEqual(r['totals']['refunded_cents'],8000)
        self.assertIn('refund_exposure',[x['issue_type'] for x in r['quality_issues']])
    def test_orphan_refund_is_quarantined(self):
        self.add('refund',[(3,'R2','NONE',100,'CAD','succeeded','2026-11-10 12:00:00')])
        self.assertEqual(self.execute()['batch_metrics']['refund']['rejected'],1)
    def test_no_payment_order_survives(self):
        self.change_source("INSERT INTO orders VALUES(507,1,'2026-11-10 09:00:00','pending','CAD',0,0)")
        self.change_source('INSERT INTO order_items VALUES(9,507,1,1,100,0)')
        r=self.execute()['orders'][-1]; self.assertEqual((r['captured_cents'],r['capture_variance_cents']),(0,-100))
    def test_source_orphan_fails_with_durable_audit(self):
        self.change_source('UPDATE orders SET customer_id=999 WHERE order_id=501')
        with self.assertRaisesRegex(ValueError,'orphan_order_customer'): self.execute()
        self.assertEqual(self.sql('SELECT status FROM ops_runs'),[('failed',)])
    def test_full_snapshot_updates_existing_source(self):
        self.execute(); self.change_source("UPDATE customers SET region='NS' WHERE customer_id=1")
        self.assertEqual(self.execute()['orders'][0]['region'],'NS')
    def test_snapshot_deleted_referenced_order_fails(self):
        self.execute(); self.change_source('DELETE FROM order_items WHERE order_id=501'); self.change_source('DELETE FROM orders WHERE order_id=501')
        with self.assertRaisesRegex(ValueError,'source_deleted_referenced_order'): self.execute()
        self.assertEqual(self.sql('SELECT COUNT(*) FROM silver_orders'),[(6,)])
    def test_injected_failure_rolls_back_and_records_failure(self):
        first=self.execute()
        with self.assertRaisesRegex(RuntimeError,'injected_failure'): self.execute(late=True,fail_at='after_ingest')
        self.assertEqual(self.sql('SELECT COUNT(*) FROM silver_payment_events'),[(9,)])
        self.assertEqual(self.sql('SELECT status FROM ops_runs'),[('succeeded',),('failed',)])
        self.assertEqual(json.loads(self.sql('SELECT report_json FROM ops_runs WHERE run_id=1')[0][0])['totals'],first['totals'])
        self.assertEqual(self.execute(late=True)['totals']['captured_cents'],29000)
    def test_ragged_rows_quarantined_not_whole_batch_failure(self):
        self.add('payment',[(20,'P9',501,100,'CAD','succeeded','2026-11-10 10:08:00','EXTRA'),(21,'P10')])
        report=self.execute()
        self.assertEqual(report['batch_metrics']['payment']['rejected'],2)
        self.assertEqual(report['totals']['captured_cents'],27000)
    def test_oversized_source_line_fails_explicitly(self):
        self.change_source('UPDATE order_items SET quantity=999999999999, unit_price_cents=999999999999 WHERE item_id=1')
        with self.assertRaisesRegex(ValueError,'line_value_exceeds_supported_range'): self.execute()
    def test_header_mismatch_fail_not_silent(self):
        (self.source.parent/'payments.csv').write_text('bad,header\n1,2\n')
        with self.assertRaisesRegex(ValueError,'event_header_mismatch'): self.execute()
        self.assertEqual(self.sql('SELECT status FROM ops_runs'),[('failed',)])
    def test_export_consistent_run_bundle(self):
        out=self.root/'reports'; r=self.execute(out=out); latest=json.loads((out/'latest.json').read_text())
        self.assertEqual(latest['run_id'],r['run_id'])
        bundle=out/('run-'+str(r['run_id']))
        self.assertEqual(json.loads((bundle/'report.json').read_text()),r)
        self.assertIn('RUN '+str(r['run_id']),(bundle/'report.html').read_text())
        self.assertEqual(self.sql('SELECT export_status FROM ops_runs'),[('exported',)])
    def test_export_failure_does_not_claim_export_success(self):
        out=self.root/'not-a-directory'; out.write_text('block')
        with self.assertRaises(FileExistsError): self.execute(out=out)
        self.assertEqual(self.sql('SELECT status,export_status FROM ops_runs'),[('succeeded','failed')])
    def test_export_recovery_keeps_pointer_consistent(self):
        from unittest.mock import patch
        import os
        out=self.root/'reports'; first=self.execute(out=out)
        original=os.replace
        def fail_pointer(src,dst):
            if str(dst).endswith('latest.json'): raise OSError('injected_pointer_failure')
            return original(src,dst)
        with patch('commerce.run.os.replace',side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError,'injected_pointer_failure'): self.execute(late=True,out=out)
        self.assertEqual(json.loads((out/'latest.json').read_text())['run_id'],first['run_id'])
        recovered=self.execute(late=True,out=out)
        pointer=json.loads((out/'latest.json').read_text())
        self.assertEqual(pointer['run_id'],recovered['run_id'])
        self.assertIn('RUN '+str(pointer['run_id']),(out/pointer['report']).read_text())
        self.assertEqual(json.loads((out/('run-'+str(pointer['run_id']))/'report.json').read_text())['run_id'],pointer['run_id'])
        self.assertEqual(self.sql('SELECT export_status FROM ops_runs'),[('exported',),('failed',),('exported',)])
    def test_recover_export_uses_persisted_snapshot_without_ingestion(self):
        from commerce.recover import recover
        first = self.execute()
        self.change_source("UPDATE customers SET region='NS' WHERE customer_id=1")
        (self.source.parent/'payments.csv').write_text('unavailable source')
        report = recover(self.db, first['run_id'], self.root/'recovered')
        self.assertEqual(report, first)
        self.assertEqual(self.sql('SELECT COUNT(*) FROM ops_runs'), [(1,)])
        self.assertEqual(self.sql('SELECT COUNT(*) FROM silver_payment_events'), [(9,)])
        self.assertEqual(self.sql('SELECT export_status FROM ops_runs'), [('exported',)])

    def test_recover_rejects_old_run_without_changing_pointer(self):
        from commerce.recover import recover
        out = self.root/'reports'
        first = self.execute(out=out)
        latest = self.execute(late=True, out=out)
        before = (out/'latest.json').read_bytes()
        with self.assertRaisesRegex(ValueError, 'refuse_to_publish_older_run'):
            recover(self.db, first['run_id'], out)
        self.assertEqual((out/'latest.json').read_bytes(), before)
        self.assertEqual(json.loads(before)['run_id'], latest['run_id'])

    def test_recover_rejects_failed_and_missing_runs(self):
        from commerce.recover import recover
        with self.assertRaises(RuntimeError):
            self.execute(fail_at='after_ingest')
        for run_id in (1, 999):
            with self.assertRaisesRegex(ValueError, 'run_has_no_committed_report'):
                recover(self.db, run_id, self.root/'reports')
        self.assertFalse((self.root/'reports').exists())

    def test_recover_missing_warehouse_does_not_create_it(self):
        from commerce.recover import recover
        missing = self.root/'missing.sqlite'
        with self.assertRaises(FileNotFoundError):
            recover(missing, 1, self.root/'reports')
        self.assertFalse(missing.exists())

    def test_recover_failure_then_retry_preserves_exact_report(self):
        from commerce.recover import recover
        first = self.execute()
        blocker = self.root/'file'; blocker.write_text('not a directory')
        with self.assertRaises(FileExistsError):
            recover(self.db, first['run_id'], blocker)
        self.assertEqual(self.sql('SELECT status, export_status FROM ops_runs'), [('succeeded', 'failed')])
        out = self.root/'reports'
        self.assertEqual(recover(self.db, first['run_id'], out), first)
        self.assertEqual(json.loads((out/'run-1/report.json').read_text()), first)
        self.assertEqual(self.sql('SELECT status, export_status FROM ops_runs'), [('succeeded', 'exported')])

    def test_regional_rollup_conserves_totals(self):
        r=self.execute()
        self.assertEqual(sum(x['captured_cents'] for x in r['regions']),r['totals']['captured_cents'])
    def test_inputs_not_modified(self):
        before=self.source.read_bytes(); self.execute(); self.assertEqual(before,self.source.read_bytes())

if __name__=='__main__': unittest.main()
