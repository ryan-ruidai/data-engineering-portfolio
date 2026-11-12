SELECT
 (SELECT COUNT(*) FROM payment_events) AS raw_events,
 (SELECT COUNT(*) FROM latest_payments) AS latest_payments,
 (SELECT COUNT(*) FROM payment_events) -
 (SELECT COUNT(*) FROM latest_payments) AS superseded_events,
 (SELECT COUNT(*) FROM successful_payments) AS successful_payments,
 (SELECT COUNT(*) FROM latest_payments WHERE status <> 'succeeded') AS non_successful_payments;
