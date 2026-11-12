"""Multi-source retail batch ETL; stdlib, SQLite, CAD integer cents, UTC timestamps."""
import argparse
import csv
import hashlib
import html
import io
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .fixtures import TABLES, PAY_FIELDS, REF_FIELDS, create_sources

ROOT=Path(__file__).resolve().parents[1]
EVENT_COLS={'payment':PAY_FIELDS,'refund':REF_FIELDS}

def now():
    return datetime.now(timezone.utc).isoformat()

def connect(path):
    db=sqlite3.connect(str(path),timeout=10)
    db.row_factory=sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''
    CREATE TABLE IF NOT EXISTS ops_runs(run_id INTEGER PRIMARY KEY,started_at TEXT NOT NULL,
      finished_at TEXT,status TEXT NOT NULL,error TEXT,manifest_json TEXT,metrics_json TEXT,report_json TEXT,
      export_status TEXT NOT NULL DEFAULT 'not_attempted');
    CREATE TABLE IF NOT EXISTS raw_snapshots(run_id INTEGER NOT NULL REFERENCES ops_runs,
      entity TEXT NOT NULL,row_number INTEGER NOT NULL,payload_json TEXT NOT NULL,
      PRIMARY KEY(run_id,entity,row_number));
    CREATE TABLE IF NOT EXISTS raw_event_rows(run_id INTEGER NOT NULL REFERENCES ops_runs,
      entity TEXT NOT NULL,row_number INTEGER NOT NULL,payload_json TEXT NOT NULL,
      disposition TEXT NOT NULL,reason TEXT,PRIMARY KEY(run_id,entity,row_number));
    CREATE TABLE IF NOT EXISTS quality_issues(run_id INTEGER NOT NULL REFERENCES ops_runs,
      issue_type TEXT NOT NULL,entity_id TEXT NOT NULL,detail TEXT NOT NULL);
    ''')
    for table,cols in TABLES.items():
        db.execute('CREATE TABLE IF NOT EXISTS silver_'+table+'('+','.join(k+' '+v for k,v in cols)+')')
    for entity,cols in EVENT_COLS.items():
        db.execute('CREATE TABLE IF NOT EXISTS silver_'+entity+'_events ('+
          ','.join(c+(' INTEGER' if c in ('event_id','order_id','amount_cents') else ' TEXT')+' NOT NULL' for c in cols)+
          ',first_run INTEGER NOT NULL REFERENCES ops_runs,source_line INTEGER NOT NULL,PRIMARY KEY(event_id))')
    # executescript only during initialization, never inside the batch transaction.
    db.executescript((ROOT/'sql/commerce/marts.sql').read_text())
    db.commit()
    return db

def integer(v,minimum=0):
    if not re.fullmatch(r'[0-9]{1,12}',str(v)) or int(v)<minimum:
        raise ValueError('invalid_nonnegative_integer')
    return int(v)

def timestamp(v):
    try:
        parsed=datetime.strptime(v,'%Y-%m-%d %H:%M:%S')
        if parsed.strftime('%Y-%m-%d %H:%M:%S')!=v: raise ValueError()
    except (ValueError,TypeError):
        raise ValueError('invalid_utc_timestamp')
    return v

def snapshot(path):
    """Consistent full-source snapshot. Never mutate a caller's source database."""
    uri=Path(path).resolve().as_uri()+'?mode=ro'
    source=sqlite3.connect(uri,uri=True)
    source.row_factory=sqlite3.Row
    result={}
    try:
        source.execute('BEGIN')
        for table,cols in TABLES.items():
            names=[x['name'] for x in source.execute('PRAGMA table_info('+table+')')]
            if names!=[x[0] for x in cols]: raise ValueError('source_schema_mismatch:'+table)
            result[table]=[dict(row) for row in source.execute('SELECT * FROM '+table+' ORDER BY '+cols[0][0])]
    finally:
        source.close()
    customers={r['customer_id'] for r in result['customers']}
    products={r['product_id'] for r in result['products']}
    orders={r['order_id'] for r in result['orders']}
    for table,rows in result.items():
        for row in rows:
            for col,val in row.items():
                if col.endswith('_id'): integer(val,1)
                if val is None: raise ValueError('null_source_field:'+table+'.'+col)
    for row in result['orders']:
        if row['customer_id'] not in customers: raise ValueError('orphan_order_customer')
        if row['status'] not in ('pending','fulfilled','cancelled'): raise ValueError('invalid_order_status')
        if row['currency']!='CAD': raise ValueError('unsupported_order_currency')
        timestamp(row['ordered_at']); integer(row['tax_cents']); integer(row['shipping_cents'])
    for row in result['order_items']:
        if row['order_id'] not in orders or row['product_id'] not in products: raise ValueError('orphan_order_item')
        qty=integer(row['quantity'],1); price=integer(row['unit_price_cents']); discount=integer(row['discount_cents'])
        if qty*price>10**15: raise ValueError('line_value_exceeds_supported_range')
        if discount>qty*price: raise ValueError('discount_exceeds_line_value')
    if orders!={r['order_id'] for r in result['order_items']}: raise ValueError('order_without_items')
    return result

def parse_event(entity,row):
    cols=EVENT_COLS[entity]
    if set(row)!=set(cols) or any(v is None for v in row.values()): raise ValueError('invalid_event_columns')
    row={k:v.strip() for k,v in row.items()}
    for k in ('event_id','amount_cents'):
        row[k]=integer(row[k],1 if k=='event_id' else 0)
    if entity=='payment': row['order_id']=integer(row['order_id'],1)
    if entity=='refund' and row['amount_cents']==0: raise ValueError('zero_refund')
    for k in (('payment_id',) if entity=='payment' else ('refund_id','payment_id')):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,32}',row[k]): raise ValueError('invalid_business_id')
    if row['currency']!='CAD': raise ValueError('unsupported_event_currency')
    allowed=('pending','succeeded','voided') if entity=='payment' else ('pending','succeeded','failed')
    if row['status'] not in allowed: raise ValueError('invalid_event_status')
    timestamp(row['updated_at'])
    return row

def ingest_events(db,run_id,entity,payload):
    reader=csv.DictReader(io.StringIO(payload.decode('utf-8-sig')))
    cols=EVENT_COLS[entity]
    if reader.fieldnames!=cols: raise ValueError('event_header_mismatch:'+entity)
    stats={'input':0,'accepted':0,'duplicates':0,'rejected':0}
    table='silver_'+entity+'_events'
    for line,raw in enumerate(reader,2):
        stats['input']+=1; disposition='accepted'; reason=None
        try:
            row=parse_event(entity,raw)
            existing=db.execute('SELECT '+','.join(cols)+' FROM '+table+' WHERE event_id=?',(row['event_id'],)).fetchone()
            if existing:
                if dict(existing)!=row: raise ValueError('immutable_event_conflict')
                disposition='duplicates'
            else:
                key='payment_id' if entity=='payment' else 'refund_id'
                parent='order_id' if entity=='payment' else 'payment_id'
                prior=db.execute('SELECT '+parent+' FROM '+table+' WHERE '+key+'=? LIMIT 1',(row[key],)).fetchone()
                if prior and prior[0]!=row[parent]: raise ValueError('immutable_parent_conflict')
                if entity=='payment':
                    if not db.execute('SELECT 1 FROM silver_orders WHERE order_id=?',(row['order_id'],)).fetchone(): raise ValueError('unknown_order_retryable')
                elif not db.execute('SELECT 1 FROM silver_payment_events WHERE payment_id=?',(row['payment_id'],)).fetchone():
                    raise ValueError('unknown_payment_retryable')
                db.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in range(len(cols)+2))+')',tuple(row[c] for c in cols)+(run_id,line))
        except (ValueError,TypeError) as exc:
            disposition='rejected'; reason=str(exc)
        stats[disposition]+=1
        db.execute('INSERT INTO raw_event_rows VALUES(?,?,?,?,?,?)',(run_id,entity,line,json.dumps(raw),disposition,reason))
    if stats['input']!=stats['accepted']+stats['duplicates']+stats['rejected']:
        raise RuntimeError('batch_count_conservation_failed')
    return stats

def issue(db,run_id,kind,entity,detail):
    db.execute('INSERT INTO quality_issues VALUES(?,?,?,?)',(run_id,kind,str(entity),detail))

def build_report(db,run_id,stats):
    rows=[dict(r) for r in db.execute('SELECT * FROM gold_order_reconciliation ORDER BY order_id')]
    for row in rows:
        if row['capture_variance_cents']:
            issue(db,run_id,'capture_variance',row['order_id'],'captured minus collectible: '+str(row['capture_variance_cents'])+' cents')
    for row in db.execute('''SELECT r.payment_id,SUM(r.amount_cents) refunds,p.amount_cents,p.status
       FROM silver_current_refunds r JOIN silver_current_payments p USING(payment_id)
       WHERE r.status='succeeded' GROUP BY r.payment_id,p.amount_cents,p.status'''):
        if row['status']!='succeeded' or row['refunds']>row['amount_cents']:
            issue(db,run_id,'refund_exposure',row['payment_id'],'successful refunds exceed current captured basis or capture is not succeeded')
    sums={k:sum(r[k] for r in rows) for k in ('original_order_total_cents','collectible_cents','captured_cents','refunded_cents','net_payment_cents','capture_variance_cents')}
    payment_total=db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM silver_current_payments WHERE status='succeeded'").fetchone()[0]
    refund_total=db.execute("SELECT COALESCE(SUM(amount_cents),0) FROM silver_current_refunds WHERE status='succeeded'").fetchone()[0]
    # Every order and accepted financial parent must survive model joins.
    if len(rows)!=db.execute('SELECT COUNT(*) FROM silver_orders').fetchone()[0]:
        raise RuntimeError('order_coverage_failed')
    if sums['captured_cents']!=payment_total or sums['refunded_cents']!=refund_total:
        raise RuntimeError('financial_conservation_failed')
    if sums['net_payment_cents']!=payment_total-refund_total:
        raise RuntimeError('net_arithmetic_failed')
    rejected=sum(s['rejected'] for s in stats.values())
    if rejected: issue(db,run_id,'quarantine',run_id,str(rejected)+' event rows rejected; inspect raw_event_rows before certifying results')
    issues=[dict(r) for r in db.execute('SELECT issue_type,entity_id,detail FROM quality_issues WHERE run_id=?',(run_id,))]
    regions=[dict(r) for r in db.execute('''SELECT region,COUNT(*) orders,SUM(collectible_cents) collectible_cents,
      SUM(captured_cents) captured_cents,SUM(refunded_cents) refunded_cents,SUM(net_payment_cents) net_payment_cents
      FROM gold_order_reconciliation GROUP BY region ORDER BY region''')]
    return {'run_id':run_id,'generated_at':now(),'currency':'CAD','data':'Synthetic retail demonstration',
      'metric_contract':'Current-state capture/refund snapshots, not accounting revenue or bank settlement.',
      'source_mode':'Full retail snapshot plus immutable event history; no as-of cutoff.',
      'totals':sums,'orders':rows,'regions':regions,'quality_issues':issues,'batch_metrics':stats,
      'payments':[dict(r) for r in db.execute('SELECT * FROM silver_current_payments ORDER BY payment_id')],
      'refunds':[dict(r) for r in db.execute('SELECT * FROM silver_current_refunds ORDER BY refund_id')],
      'checks':{'order_coverage':True,'capture_conservation':True,'refund_conservation':True,'net_arithmetic':True}}

def render(report):
    esc=lambda v:html.escape(str(v))
    money=lambda v:f"${v/100:,.2f}"
    cards=''.join('<article><small>'+esc(k.replace('_cents','').replace('_',' '))+'</small><strong>'+money(v)+'</strong></article>' for k,v in report['totals'].items())
    table=''.join('<tr>'+''.join('<td>'+esc(r[k] if not k.endswith('_cents') else money(r[k]))+'</td>' for k in ('order_id','status','region','collectible_cents','captured_cents','refunded_cents','net_payment_cents','capture_variance_cents'))+'</tr>' for r in report['orders'])
    issues=''.join('<li><b>'+esc(x['issue_type'])+' / '+esc(x['entity_id'])+'</b>: '+esc(x['detail'])+'</li>' for x in report['quality_issues']) or '<li>No model exceptions in this run.</li>'
    detail=''.join('<details><summary>'+esc(name.title())+' · latest accepted state</summary><pre>'+esc(json.dumps(report[name],indent=2))+'</pre></details>' for name in ('payments','refunds'))
    return '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Retail payment assurance</title><style>
    body{font:16px system-ui;background:#f4f6fa;color:#17283d;margin:0;padding:40px;max-width:1180px;margin:auto}h1{font-size:38px;margin-bottom:12px}.tag{color:#446788}section{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:24px 0}article{background:white;padding:20px;border:1px solid #dbe4ef;border-radius:12px}small{display:block;text-transform:uppercase;font-size:11px;letter-spacing:1px}strong{display:block;font-size:28px;margin-top:12px}table{border-collapse:collapse;width:100%;background:white}td,th{text-align:right;padding:12px;border-bottom:1px solid #dbe4ef}td:first-child,th:first-child{text-align:left}.scroll{overflow:auto}li{padding:7px}footer{margin-top:30px;font-size:13px;color:#456}p{line-height:1.6}details{background:white;padding:16px;margin:12px 0;border-radius:10px}summary{cursor:pointer;font-weight:600}pre{overflow:auto;font-size:13px}</style>'''+f'''<p class="tag">SYNTHETIC RETAIL · CAD · RUN {report['run_id']}</p><h1>Retail payment assurance</h1><p>From orders and line items to payment states, refunds and actionable reconciliation exceptions.</p><section>{cards}</section><h2>Order-level reconciliation</h2><p>Capture variance compares gross captured with collectible order value. Refunds are shown separately; net payment is not revenue. Cancelled orders have zero collectible value.</p><div class="scroll"><table><thead><tr><th>Order</th><th>Status</th><th>Region</th><th>Collectible</th><th>Captured</th><th>Refunded</th><th>Net payment</th><th>Variance</th></tr></thead><tbody>{table}</tbody></table></div><h2>Exceptions for investigation</h2><ul>{issues}</ul><h2>Transaction drilldown</h2>{detail}<footer>Generated {esc(report['generated_at'])}. Fictional full retail snapshot + processor event CSV exports. Conservation checks passed. No bank settlement feed, accounting revenue recognition, FX, or production deployment is represented.</footer></html>'''

def export_report(db,report,out):
    """Immutable per-run bundle. Readers see a complete bundle via atomic pointer replace."""
    out=Path(out); out.mkdir(parents=True,exist_ok=True)
    target=out/('run-'+str(report['run_id'])); target.mkdir(exist_ok=True)
    for name,content in [('report.json',json.dumps(report,indent=2)),('report.html',render(report))]:
        temp=target/(name+'.tmp'); temp.write_text(content,encoding='utf-8'); os.replace(str(temp),str(target/name))
    pointer=out/'latest.json.tmp'
    pointer.write_text(json.dumps({'run_id':report['run_id'],'report':'run-'+str(report['run_id'])+'/report.html'}),encoding='utf-8')
    os.replace(str(pointer),str(out/'latest.json'))
    db.execute("UPDATE ops_runs SET export_status='exported' WHERE run_id=?",(report['run_id'],)); db.commit()

def run(warehouse,source,payments,refunds,out=None,fail_at=None):
    db=connect(warehouse)
    run_id=db.execute("INSERT INTO ops_runs(started_at,status) VALUES(?,'running')",(now(),)).lastrowid
    db.commit()
    try:
        retail=snapshot(source)
        payloads={'payment':Path(payments).read_bytes(),'refund':Path(refunds).read_bytes()}
        manifest={k:{'sha256':hashlib.sha256(v).hexdigest(),'bytes':len(v)} for k,v in payloads.items()}
        manifest['retail_snapshot']={'sha256':hashlib.sha256(json.dumps(retail,sort_keys=True).encode()).hexdigest(),'rows':{k:len(v) for k,v in retail.items()}}
        db.execute('UPDATE ops_runs SET manifest_json=? WHERE run_id=?',(json.dumps(manifest),run_id)); db.commit()
        db.execute('BEGIN IMMEDIATE')
        for table,rows in retail.items():
            db.execute('DELETE FROM silver_'+table)
            for line,row in enumerate(rows,1):
                db.execute('INSERT INTO raw_snapshots VALUES(?,?,?,?)',(run_id,table,line,json.dumps(row,sort_keys=True)))
                db.execute('INSERT INTO silver_'+table+' VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
        # Do not silently lose history if a full snapshot removes a referenced order.
        if db.execute('SELECT 1 FROM silver_payment_events p LEFT JOIN silver_orders o USING(order_id) WHERE o.order_id IS NULL LIMIT 1').fetchone():
            raise ValueError('source_deleted_referenced_order')
        stats={entity:ingest_events(db,run_id,entity,payloads[entity]) for entity in ('payment','refund')}
        if fail_at=='after_ingest': raise RuntimeError('injected_failure_after_ingest')
        report=build_report(db,run_id,stats)
        db.execute("UPDATE ops_runs SET finished_at=?,status='succeeded',metrics_json=?,report_json=? WHERE run_id=?",(now(),json.dumps(stats),json.dumps(report),run_id))
        db.commit()
    except Exception as exc:
        db.rollback()
        db.execute("UPDATE ops_runs SET finished_at=?,status='failed',error=? WHERE run_id=?",(now(),str(exc),run_id)); db.commit(); db.close()
        raise
    try:
        if out is not None: export_report(db,report,out)
    except Exception:
        db.execute("UPDATE ops_runs SET export_status='failed' WHERE run_id=?",(run_id,)); db.commit()
        raise
    finally: db.close()
    return report

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workdir',type=Path,default=Path('build/commerce'))
    parser.add_argument('--batch',choices=['base','late'],default='base')
    args=parser.parse_args(); args.workdir.mkdir(parents=True,exist_ok=True)
    inputs=args.workdir/'inputs'
    if not (inputs/'retail.sqlite').exists(): create_sources(inputs)
    suffix='_late' if args.batch=='late' else ''
    report=run(args.workdir/'warehouse.sqlite',inputs/'retail.sqlite',inputs/('payments'+suffix+'.csv'),inputs/('refunds'+suffix+'.csv'),args.workdir/'reports')
    print(json.dumps({'run_id':report['run_id'],'totals':report['totals'],'batch_metrics':report['batch_metrics'],'exceptions':len(report['quality_issues'])},indent=2))
    print('Open',args.workdir/'reports'/('run-'+str(report['run_id']))/'report.html')

if __name__=='__main__': main()
