-- sql/views/v_variant_attribution.sql (revised for dev_nexus)
create or replace view dev_nexus.v_variant_attribution as
select
    a.variant_id,
    a.channel,
    count(*) as total_sent,
    count(*) filter (where a.status = 'completed' or a.result_summary = 'delivered') as delivered,
    count(*) filter (where a.status = 'failed') as failed,
    round(
        100.0 * count(*) filter (where a.status = 'completed' or a.result_summary = 'delivered')
        / nullif(count(*), 0),
        2
    ) as delivery_rate
from dev_nexus.campaign_activity a
group by a.variant_id, a.channel;
