CREATE VIEW successful_payments AS
SELECT event_id, payment_id, order_id, amount, updated_at
FROM latest_payments
WHERE status = 'succeeded';
