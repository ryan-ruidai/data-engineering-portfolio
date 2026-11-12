-- Grain is one row per ORDER. Aggregate each one-to-many source before joining.
DROP VIEW IF EXISTS gold_order_reconciliation;
DROP VIEW IF EXISTS silver_current_refunds;
DROP VIEW IF EXISTS silver_current_payments;
CREATE VIEW silver_current_payments AS
SELECT event_id,payment_id,order_id,amount_cents,currency,status,updated_at
FROM (SELECT *, ROW_NUMBER() OVER(PARTITION BY payment_id ORDER BY updated_at DESC,event_id DESC) rn
FROM silver_payment_events) WHERE rn=1;
CREATE VIEW silver_current_refunds AS
SELECT event_id,refund_id,payment_id,amount_cents,currency,status,updated_at
FROM (SELECT *, ROW_NUMBER() OVER(PARTITION BY refund_id ORDER BY updated_at DESC,event_id DESC) rn
FROM silver_refund_events) WHERE rn=1;
CREATE VIEW gold_order_reconciliation AS
WITH lines AS (
 SELECT order_id,SUM(quantity*unit_price_cents-discount_cents) item_net_cents,COUNT(*) line_count
 FROM silver_order_items GROUP BY order_id
), paid AS (
 SELECT order_id,SUM(amount_cents) captured_cents,COUNT(*) payment_count
 FROM silver_current_payments WHERE status='succeeded' GROUP BY order_id
), refunded AS (
 SELECT p.order_id,SUM(r.amount_cents) refunded_cents
 FROM silver_current_refunds r JOIN silver_current_payments p USING(payment_id)
 WHERE r.status='succeeded' GROUP BY p.order_id
)
SELECT o.order_id,o.customer_id,c.region,o.ordered_at,o.status,o.currency,
 l.line_count,l.item_net_cents,o.tax_cents,o.shipping_cents,
 l.item_net_cents+o.tax_cents+o.shipping_cents AS original_order_total_cents,
 CASE WHEN o.status='cancelled' THEN 0 ELSE l.item_net_cents+o.tax_cents+o.shipping_cents END AS collectible_cents,
 COALESCE(p.payment_count,0) payment_count,COALESCE(p.captured_cents,0) captured_cents,
 COALESCE(r.refunded_cents,0) refunded_cents,
 COALESCE(p.captured_cents,0)-COALESCE(r.refunded_cents,0) net_payment_cents,
 COALESCE(p.captured_cents,0)-CASE WHEN o.status='cancelled' THEN 0 ELSE l.item_net_cents+o.tax_cents+o.shipping_cents END AS capture_variance_cents
FROM silver_orders o JOIN silver_customers c USING(customer_id)
JOIN lines l USING(order_id) LEFT JOIN paid p USING(order_id) LEFT JOIN refunded r USING(order_id);
