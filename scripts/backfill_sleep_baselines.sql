-- Backfill missing sleep baselines on PersonalModel using onboarding-tier population defaults.
-- Safe: only updates NULL fields; does not overwrite calibrated values.
--
-- Usage (Railway):
--   railway connect postgres
--   \i scripts/backfill_sleep_baselines.sql
--
-- Usage (psql):
--   psql "$DATABASE_URL" -f scripts/backfill_sleep_baselines.sql

with tiers as (
  select
    u.id as user_id,
    coalesce(u.onboarding->>'exercise_frequency', '1-3x/week') as freq,
    case
      when coalesce(u.onboarding->>'exercise_frequency', '1-3x/week') = 'rarely' then 32.0
      when coalesce(u.onboarding->>'exercise_frequency', '1-3x/week') = '4+/week' then 60.0
      else 44.0
    end as sleep_avg_seed,
    case
      when coalesce(u.onboarding->>'exercise_frequency', '1-3x/week') = 'rarely' then 52.0
      when coalesce(u.onboarding->>'exercise_frequency', '1-3x/week') = '4+/week' then 88.0
      else 66.0
    end as sleep_ceiling_seed
  from users u
),
to_update as (
  select
    pm.user_id,
    pm.rmssd_sleep_avg,
    pm.rmssd_sleep_ceiling,
    t.sleep_avg_seed,
    least(t.sleep_ceiling_seed, 110.0) as sleep_ceiling_seed_capped
  from personal_models pm
  join tiers t on t.user_id = pm.user_id
  where pm.rmssd_sleep_avg is null
     or pm.rmssd_sleep_ceiling is null
)
update personal_models pm
set
  rmssd_sleep_avg = coalesce(pm.rmssd_sleep_avg, tu.sleep_avg_seed),
  rmssd_sleep_ceiling = coalesce(pm.rmssd_sleep_ceiling, tu.sleep_ceiling_seed_capped)
from to_update tu
where pm.user_id = tu.user_id;

