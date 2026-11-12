SELECT order_id, COUNT(*) AS successful_payment_count,
       SUM(amount) AS current_successful_payment_amount
FROM successful_payments
GROUP BY order_id
ORDER BY order_id;
