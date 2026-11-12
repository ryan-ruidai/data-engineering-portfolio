"""Isolated logic tests: SQLite, not a MySQL integration test."""
import csv
import sqlite3
import unittest
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalize(rows):
    return [(int(r[0]), r[1], int(r[2]), Decimal(str(r[3])), r[4]) for r in rows]


class PaymentPipelineTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript((ROOT / 'sql/01_schema.sql').read_text())
        with (ROOT / 'data/synthetic/payment_events.csv').open(newline='') as f:
            self.raw = list(csv.DictReader(f))
        self.db.executemany('INSERT INTO payment_events VALUES (?,?,?,?,?,?)',
            [(int(r['event_id']),r['payment_id'],int(r['order_id']),r['amount'],r['status'],r['updated_at']) for r in self.raw])
        for name in ['02_latest_payments.sql','03_successful_payments.sql']:
            self.db.executescript((ROOT / 'sql' / name).read_text())
        with (ROOT / 'tests/expected_successful_payments.csv').open(newline='') as f:
            self.expected = normalize(list(csv.reader(f))[1:])

    def successful(self):
        return normalize(self.db.execute('SELECT * FROM successful_payments ORDER BY payment_id').fetchall())

    def test_exact_expected_output(self):
        self.assertEqual(self.successful(), self.expected)

    def test_reference_query_matches_refactor(self):
        self.assertEqual(normalize(self.db.execute((ROOT/'sql/payment_snapshot.sql').read_text()).fetchall()), self.expected)

    def test_latest_voided_excludes_prior_success(self):
        self.assertEqual(self.db.execute("SELECT event_id,status FROM latest_payments WHERE payment_id='P101'").fetchone(), (105,'voided'))
        self.assertNotIn('P101',[r[1] for r in self.successful()])

    def test_equal_time_tie_break(self):
        self.assertEqual(self.db.execute("SELECT event_id FROM latest_payments WHERE payment_id='P100'").fetchone(), (103,))

    def test_zero_retained(self):
        self.assertEqual(self.successful()[-1][3], Decimal('0.00'))

    def test_latest_amount_correction(self):
        self.assertEqual(self.db.execute("SELECT event_id,amount FROM latest_payments WHERE payment_id='P105'").fetchone(), (110,90))

    def test_multiple_payments_one_order_and_total(self):
        summary=self.db.execute((ROOT/'sql/04_order_summary.sql').read_text()).fetchall()
        self.assertEqual(summary, [(501,1,80),(503,2,75),(505,1,90),(506,1,0)])
        self.assertEqual(sum((r[3] for r in self.successful()),Decimal('0')),Decimal('245.00'))

    def test_reconciliation(self):
        self.assertEqual(self.db.execute((ROOT/'sql/05_reconciliation.sql').read_text()).fetchone(), (11,7,4,5,2))

    def test_repeat_query_stable_and_source_unchanged(self):
        before=self.db.execute('SELECT * FROM payment_events ORDER BY event_id').fetchall()
        self.assertEqual(self.successful(),self.successful())
        self.assertEqual(before,self.db.execute('SELECT * FROM payment_events ORDER BY event_id').fetchall())

    def test_wrong_filter_order_negative_control(self):
        wrong=self.db.execute('''SELECT payment_id FROM (
          SELECT payment_id,ROW_NUMBER() OVER (PARTITION BY payment_id ORDER BY updated_at DESC,event_id DESC) rn
          FROM payment_events WHERE status='succeeded'
        ) a WHERE rn=1 ORDER BY payment_id''').fetchall()
        self.assertIn(('P101',),wrong)
        self.assertNotEqual(wrong,[(r[1],) for r in self.expected])

if __name__ == '__main__':
    unittest.main()
