-- Snapshot reference query; standalone table name for isolated execution.
select
    event_id
  , payment_id
  , order_id
  , amount
  , updated_at
from
(
    select
        event_id
      , payment_id
      , order_id
      , amount
      , updated_at
      , status
      , row_number() over(
            partition by payment_id
            order by updated_at desc, event_id desc
        ) as rn
    from payment_events
) a
where status = 'succeeded' and rn = 1
order by payment_id;

