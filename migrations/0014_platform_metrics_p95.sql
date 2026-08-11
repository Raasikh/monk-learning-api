-- 0014: the platform metrics sampler (app/main.py) writes
-- p95_lease_acquisition_ms on every 30s sample, but 0009 never created the
-- column — every sample logged a PGRST204 warning and the p95 was dropped.
alter table drona_platform_metrics
  add column if not exists p95_lease_acquisition_ms numeric;
