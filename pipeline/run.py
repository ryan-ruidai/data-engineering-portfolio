"""Small transactional batch pipeline. Standard library only; synthetic CAD events."""
import argparse
import csv
import hashlib
import html
import json
import re
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

FIELDS = ['event_id', 'payment_id', 'order_id', 'amount', 'status', 'updated_at']
SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs(run_id INTEGER PRIMARY KEY, source_sha256 TEXT NOT NULL,
 started_at TEXT NOT NULL, input_count INTEGER, inserted_count INTEGER,
 duplicate_count INTEGER, rejected_count INTEGER, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS raw_rows(source_sha256 TEXT, line INTEGER, payload TEXT NOT NULL,
 first_run INTEGER NOT NULL REFERENCES runs(run_id), PRIMARY KEY(source_sha256,line));
CREATE TABLE IF NOT EXISTS rejected_rows(source_sha256 TEXT, line INTEGER, reason TEXT NOT NULL,
 PRIMARY KEY(source_sha256,line), FOREIGN KEY(source_sha256,line) REFERENCES raw_rows(source_sha256,line));
CREATE TABLE IF NOT EXISTS clean_events(event_id INTEGER PRIMARY KEY, payment_id TEXT NOT NULL,
 order_id INTEGER NOT NULL, amount_cents INTEGER NOT NULL CHECK(amount_cents>=0),
 status TEXT NOT NULL CHECK(status IN ('pending','succeeded','voided')), updated_at TEXT NOT NULL,
 source_sha256 TEXT NOT NULL, source_line INTEGER NOT NULL,
 FOREIGN KEY(source_sha256,source_line) REFERENCES raw_rows(source_sha256,line));
CREATE VIEW IF NOT EXISTS current_payments AS SELECT event_id,payment_id,order_id,amount_cents,status,updated_at
 FROM (SELECT *,ROW_NUMBER() OVER(PARTITION BY payment_id ORDER BY updated_at DESC,event_id DESC) rn FROM clean_events) WHERE rn=1;
CREATE VIEW IF NOT EXISTS successful_snapshot AS SELECT * FROM current_payments WHERE status='succeeded';
CREATE VIEW IF NOT EXISTS order_snapshot AS SELECT order_id,COUNT(*) payment_count,SUM(amount_cents) amount_cents
 FROM successful_snapshot GROUP BY order_id;
'''


def validate(row):
    if set(row) != set(FIELDS) or any(row[k] is None for k in FIELDS):
        raise ValueError('invalid_columns')
    row = {k: v.strip() for k, v in row.items()}
    if not re.fullmatch(r'[1-9][0-9]{0,14}', row['event_id']) or not re.fullmatch(r'[1-9][0-9]{0,14}', row['order_id']):
        raise ValueError('invalid_identifier')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}', row['payment_id']):
        raise ValueError('invalid_payment_id')
    if row['status'] not in ('pending', 'succeeded', 'voided'):
        raise ValueError('invalid_status')
    if not re.fullmatch(r'[0-9]{1,8}(\.[0-9]{1,2})?', row['amount']):
        raise ValueError('invalid_amount')
    cents = int(Decimal(row['amount']) * 100)
    try:
        date = datetime.strptime(row['updated_at'], '%Y-%m-%d %H:%M:%S')
        if date.strftime('%Y-%m-%d %H:%M:%S') != row['updated_at']:
            raise ValueError()
    except ValueError:
        raise ValueError('invalid_timestamp')
    return (int(row['event_id']),row['payment_id'],int(row['order_id']),cents,row['status'],row['updated_at'])


def connect(path):
    db = sqlite3.connect(str(path), timeout=10)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript(SCHEMA)
    return db


def ingest(db, path):
    """One atomic transaction per UTF-8 CSV batch; existing immutable event IDs cannot change."""
    payload = Path(path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    import io
    reader = csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    if reader.fieldnames != FIELDS:
        raise ValueError('CSV header must exactly match the documented contract')
    with db:
        db.execute('BEGIN IMMEDIATE')
        run = db.execute("INSERT INTO runs(source_sha256,started_at,status) VALUES(?,?,?)",
            (digest,datetime.now(timezone.utc).isoformat(),'running')).lastrowid
        counts = dict(input_count=0,inserted_count=0,duplicate_count=0,rejected_count=0)
        for line,row in enumerate(reader,2):
            counts['input_count'] += 1
            db.execute('INSERT OR IGNORE INTO raw_rows VALUES(?,?,?,?)',(digest,line,json.dumps(row),run))
            try:
                values = validate(row)
                prior = db.execute('SELECT event_id,payment_id,order_id,amount_cents,status,updated_at FROM clean_events WHERE event_id=?',(values[0],)).fetchone()
                if prior is not None:
                    if prior != values:
                        raise ValueError('conflicting_event_id')
                    counts['duplicate_count'] += 1
                else:
                    db.execute('INSERT INTO clean_events VALUES(?,?,?,?,?,?,?,?)', values+(digest,line))
                    counts['inserted_count'] += 1
            except (ValueError,InvalidOperation) as exc:
                db.execute('INSERT OR IGNORE INTO rejected_rows VALUES(?,?,?)',(digest,line,str(exc)))
                counts['rejected_count'] += 1
        assert counts['input_count'] == sum(counts[k] for k in ('inserted_count','duplicate_count','rejected_count'))
        db.execute('UPDATE runs SET input_count=?,inserted_count=?,duplicate_count=?,rejected_count=?,status=? WHERE run_id=?',
            tuple(counts.values())+('completed',run))
    return dict(run_id=run,source_sha256=digest,**counts)


def metrics(db):
    scalar = lambda sql: db.execute(sql).fetchone()[0]
    events = scalar('SELECT COUNT(*) FROM clean_events')
    latest = scalar('SELECT COUNT(*) FROM current_payments')
    successes = scalar('SELECT COUNT(*) FROM successful_snapshot')
    cents = scalar('SELECT COALESCE(SUM(amount_cents),0) FROM successful_snapshot')
    orders = [dict(order_id=r[0],payment_count=r[1],amount_cents=r[2]) for r in db.execute('SELECT * FROM order_snapshot ORDER BY order_id')]
    historical = scalar('SELECT COUNT(*) FROM clean_events e WHERE NOT EXISTS (SELECT 1 FROM current_payments p WHERE p.event_id=e.event_id)')
    checks = {'event_balance':events==latest+historical,'payment_balance':latest==successes+scalar("SELECT COUNT(*) FROM current_payments WHERE status!='succeeded'"),
        'order_amount_balance':cents==sum(r['amount_cents'] for r in orders), 'order_payment_balance':successes==sum(r['payment_count'] for r in orders)}
    return dict(clean_events=events,latest_payments=latest,historical_events=historical,successful_payments=successes,
        successful_snapshot_cents=cents,orders=orders,checks=checks,
        rejected_rows=scalar('SELECT COUNT(*) FROM rejected_rows'),
        rejection_reasons=dict(db.execute('SELECT reason,COUNT(*) FROM rejected_rows GROUP BY reason').fetchall()))


def report(db, destination):
    m = metrics(db)
    latest_run = db.execute('SELECT run_id,started_at,input_count,inserted_count,duplicate_count,rejected_count FROM runs ORDER BY run_id DESC LIMIT 1').fetchone()
    esc = html.escape
    money = lambda cents: format(Decimal(cents)/100,'.2f')
    rows = ''.join('<tr><td>{}</td><td>{}</td><td>{}</td></tr>'.format(r['order_id'],r['payment_count'],money(r['amount_cents'])) for r in m['orders'])
    checks = ''.join('<li>{}: {}</li>'.format(esc(k),'PASS' if v else 'FAIL') for k,v in m['checks'].items())
    reasons = ''.join('<li>{}: {}</li>'.format(esc(k),v) for k,v in m['rejection_reasons'].items()) or '<li>No rejected records in this database.</li>'
    cards = ''.join('<article><strong>{}</strong><span>{}</span></article>'.format(v,esc(k)) for k,v in [('Accepted events',m['clean_events']),('Latest payments',m['latest_payments']),('Successful payments',m['successful_payments']),('Snapshot CAD',money(m['successful_snapshot_cents']))])
    page = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Payment pipeline | quality and snapshot report</title><style>
body{font:16px/1.6 system-ui,sans-serif;color:#16324a;background:#f3f6f9;margin:0}main{max-width:1040px;margin:auto;padding:32px 20px}h1{line-height:1.2;font-size:2.4rem}h2{margin-top:2rem}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:16px}article,section{background:white;border:1px solid #ccd9e2;border-radius:12px;padding:20px}strong{font-size:2rem;display:block}span{display:block}table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:10px;border-bottom:1px solid #ddd}.note{border-left:5px solid #d28200;padding:12px;background:#fff3dd}code{overflow-wrap:anywhere}footer{margin-top:30px;color:#42576a}</style><main>
<p>SYNTHETIC DATA · LOCAL BATCH DEMO</p><h1>Payment snapshot &amp; data quality</h1><p class="note">Current successful payment snapshot amount is not revenue, profit, settlement, or cash received. CAD only. UTC business timestamps. Latest state first; then filter succeeded.</p><div class="cards">'''+cards+'''</div><h2>Order-level snapshot</h2><section><table><caption>One row per order with currently successful payments</caption><thead><tr><th scope="col">Order</th><th scope="col">Payment count</th><th scope="col">CAD snapshot amount</th></tr></thead><tbody>'''+rows+'''</tbody></table></section><h2>Reconciliation checks</h2><section><ul>'''+checks+'''</ul><p>These are internal consistency checks, not reconciliation with a bank or independent settlement ledger.</p></section><h2>Quality exceptions</h2><section><ul>'''+reasons+'''</ul><p>Rejected records stay in quarantine and never enter the accepted-event or snapshot layers. Counts here are unique source-file/row records, not cumulative rejection attempts.</p></section><h2>Latest batch</h2><section><p>Run / UTC time / input / inserted / duplicate / rejected:</p><code>'''+esc(str(latest_run))+'''</code><p>Every completed batch is logged; failed transactions have no durable run record; replay leaves business tables unchanged. Older arriving events are kept without replacing a newer business state.</p></section><footer>Portfolio prototype. SQLite + integer cents. No production, cloud, or financial certification claimed.</footer></main></html>'''
    destination = Path(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(page,encoding='utf-8')
    destination.with_suffix('.json').write_text(json.dumps(m,indent=2)+'\n',encoding='utf-8')
    return m


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',default='data/synthetic/payment_events.csv')
    parser.add_argument('--db',default='build/payments.db')
    parser.add_argument('--report',default='build/report.html')
    args=parser.parse_args()
    Path(args.db).parent.mkdir(parents=True,exist_ok=True)
    db=connect(args.db)
    try:
        result=ingest(db,args.input)
        m=report(db,args.report)
        print(json.dumps({'batch':result,'metrics':m},indent=2))
        if not all(m['checks'].values()):
            raise SystemExit(1)
    finally:
        db.close()

if __name__=='__main__':
    main()
