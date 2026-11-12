-- Run only in a new, isolated database. No DROP, USE, or credentials.
CREATE TABLE payment_events (
 event_id BIGINT PRIMARY KEY,
 payment_id VARCHAR(10) NOT NULL,
 order_id BIGINT NOT NULL,
 amount DECIMAL(10,2) NOT NULL,
 status VARCHAR(12) NOT NULL,
 updated_at DATETIME NOT NULL
);
