"""Deterministic, entirely fictional retail source system and processor exports."""
import csv
import sqlite3
from pathlib import Path

TABLES = {
 'customers': [('customer_id','INTEGER PRIMARY KEY'),('customer_name','TEXT NOT NULL'),('region','TEXT NOT NULL')],
 'products': [('product_id','INTEGER PRIMARY KEY'),('product_name','TEXT NOT NULL'),('category','TEXT NOT NULL')],
 'orders': [('order_id','INTEGER PRIMARY KEY'),('customer_id','INTEGER NOT NULL'),('ordered_at','TEXT NOT NULL'),('status','TEXT NOT NULL'),('currency','TEXT NOT NULL'),('tax_cents','INTEGER NOT NULL'),('shipping_cents','INTEGER NOT NULL')],
 'order_items': [('item_id','INTEGER PRIMARY KEY'),('order_id','INTEGER NOT NULL'),('product_id','INTEGER NOT NULL'),('quantity','INTEGER NOT NULL'),('unit_price_cents','INTEGER NOT NULL'),('discount_cents','INTEGER NOT NULL')],
}
PAY_FIELDS = ['event_id','payment_id','order_id','amount_cents','currency','status','updated_at']
REF_FIELDS = ['event_id','refund_id','payment_id','amount_cents','currency','status','updated_at']

def write_csv(path, fields, rows):
    with Path(path).open('w',newline='',encoding='utf-8') as f:
        writer=csv.writer(f); writer.writerow(fields); writer.writerows(rows)

def create_sources(directory):
    """Refuse to overwrite an existing source DB: these are inputs, not runtime state."""
    directory=Path(directory); directory.mkdir(parents=True,exist_ok=True)
    path=directory/'retail.sqlite'
    if path.exists():
        raise FileExistsError(path)
    db=sqlite3.connect(str(path))
    for name, cols in TABLES.items():
        db.execute('CREATE TABLE '+name+'('+','.join(k+' '+v for k,v in cols)+')')
    db.executemany('INSERT INTO customers VALUES(?,?,?)',[(1,'Sample Customer A','ON'),(2,'Sample Customer B','BC'),(3,'Sample Customer C','AB')])
    db.executemany('INSERT INTO products VALUES(?,?,?)',[(1,'Sample Kit','Accessories'),(2,'Sample Cable','Accessories'),(3,'Sample Desk','Home'),(4,'Promotional Sample','Promotions')])
    db.executemany('INSERT INTO orders VALUES(?,?,?,?,?,?,?)',[
      (501,1,'2026-11-10 09:00:00','fulfilled','CAD',500,500),
      (502,2,'2026-11-10 09:10:00','fulfilled','CAD',0,0),
      (503,1,'2026-11-10 09:20:00','pending','CAD',0,0),
      (504,3,'2026-11-10 09:30:00','cancelled','CAD',0,0),
      (505,2,'2026-11-10 09:40:00','fulfilled','CAD',0,0),
      (506,3,'2026-11-10 09:50:00','fulfilled','CAD',0,0)])
    db.executemany('INSERT INTO order_items VALUES(?,?,?,?,?,?)',[
      (1,501,1,2,3000,1000),(2,501,2,2,2000,0),(3,502,3,1,8000,0),
      (4,503,1,1,3000,0),(5,503,2,1,2000,0),(6,504,1,1,3000,0),
      (7,505,4,1,0,0),(8,506,1,2,3000,0)])
    db.commit(); db.close()
    write_csv(directory/'payments.csv',PAY_FIELDS,[
      (1,'P1',501,6000,'CAD','pending','2026-11-10 10:00:00'),
      (2,'P1',501,6000,'CAD','succeeded','2026-11-10 10:01:00'),
      (3,'P2',501,4000,'CAD','succeeded','2026-11-10 10:02:00'),
      (4,'P3',502,8000,'CAD','succeeded','2026-11-10 10:03:00'),
      (5,'P4',503,2000,'CAD','succeeded','2026-11-10 10:04:00'),
      (6,'P5',504,3000,'CAD','succeeded','2026-11-10 10:05:00'),
      (7,'P5',504,3000,'CAD','voided','2026-11-10 10:06:00'),
      (8,'P6',505,0,'CAD','succeeded','2026-11-10 10:07:00'),
      (9,'P7',506,7000,'CAD','succeeded','2026-11-10 10:08:00')])
    write_csv(directory/'refunds.csv',REF_FIELDS,[
      (1,'R1','P1',1000,'CAD','pending','2026-11-10 11:00:00'),
      (2,'R1','P1',1000,'CAD','succeeded','2026-11-10 11:01:00')])
    # Delta: late older capture, split balance capture, payment correction, refund.
    write_csv(directory/'payments_late.csv',PAY_FIELDS,[
      (10,'P3',502,8000,'CAD','pending','2026-11-10 09:59:00'),
      (11,'P8',503,3000,'CAD','succeeded','2026-11-11 10:00:00'),
      (12,'P7',506,6000,'CAD','succeeded','2026-11-11 10:01:00')])
    write_csv(directory/'refunds_late.csv',REF_FIELDS,[
      (3,'R2','P3',2000,'CAD','succeeded','2026-11-11 11:00:00')])
    return path
