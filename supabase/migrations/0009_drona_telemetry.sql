-- Per-turn additions
alter table drona_turns
  add column if not exists rumik_requests smallint default 0,
  add column if not exists rumik_chars integer default 0,
  add column if not exists board_event_count smallint default 0,
  add column if not exists tts_ms integer,
  add column if not exists llm_ms integer,
  add column if not exists violations jsonb default '{}'::jsonb;

-- Per-session additions
alter table drona_sessions
  add column if not exists rumik_requests_total integer default 0,
  add column if not exists rumik_peak_rpm smallint default 0,
  add column if not exists pool_exhaustion_count smallint default 0,
  add column if not exists segments_completed smallint default 0,
  add column if not exists ended_reason text;

-- Platform-wide sampling, one row every 30s while any session is live
create table if not exists drona_platform_metrics (
  id                    bigserial primary key,
  sampled_at            timestamptz not null default now(),
  active_sessions       smallint not null,
  rumik_connections_open smallint not null,
  rumik_requests_last_60s smallint not null,
  sarvam_requests_last_60s smallint not null,
  pool_wait_ms_p95      integer
);
create index if not exists drona_platform_metrics_sampled_at_idx on drona_platform_metrics (sampled_at desc);
