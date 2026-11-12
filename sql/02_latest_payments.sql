CREATE VIEW latest_payments AS
SELECT event_id, payment_id, order_id, amount, status, updated_at
FROM (
 SELECT event_id, payment_id, order_id, amount, status, updated_at,
 ROW_NUMBER() OVER (PARTITION BY payment_id
                    ORDER BY updated_at DESC, event_id DESC) AS rn
 FROM payment_events
) ranked
WHERE rn = 1;
