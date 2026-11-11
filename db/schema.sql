-- The automation's own records. n8n keeps its executions in the separate database "n8n".

CREATE TABLE leads (
  id                 bigserial PRIMARY KEY,
  name               text NOT NULL,
  email              text NOT NULL,
  phone              text,
  service            text,
  message            text,
  source             text NOT NULL DEFAULT 'web',   -- web | simulator | daily-test | drill
  is_test            boolean NOT NULL DEFAULT false,
  received_at        timestamptz NOT NULL DEFAULT now(),
  replied_at         timestamptz,
  reply_attempts     integer NOT NULL DEFAULT 0,
  next_followup_step integer,                        -- 1..4, NULL when the sequence is over
  next_followup_at   timestamptz,
  booked_at          timestamptz,
  unsubscribed_at    timestamptz
);
CREATE INDEX leads_unreplied ON leads (received_at) WHERE replied_at IS NULL;
CREATE INDEX leads_followup  ON leads (next_followup_at) WHERE next_followup_step IS NOT NULL;

CREATE TABLE messages (
  id       bigserial PRIMARY KEY,
  lead_id  bigint NOT NULL REFERENCES leads(id),
  kind     text NOT NULL CHECK (kind IN ('reply', 'followup')),
  step     integer NOT NULL,                         -- 0 = first reply, 1..4 = follow-ups
  subject  text,
  sent_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE checks (
  id      bigserial PRIMARY KEY,
  at      timestamptz NOT NULL DEFAULT now(),
  kind    text NOT NULL,                             -- daily-test
  passed  boolean NOT NULL,
  detail  jsonb
);

CREATE TABLE incidents (
  id            bigserial PRIMARY KEY,
  opened_at     timestamptz NOT NULL DEFAULT now(),
  source        text NOT NULL,                       -- n8n-error-workflow | watchdog
  workflow      text,
  node          text,
  message       text,
  execution_id  text,
  is_drill      boolean NOT NULL DEFAULT false,
  occurrences   integer NOT NULL DEFAULT 1,          -- how many times it happened while open
  last_seen_at  timestamptz,
  resolved_at   timestamptz,
  resolution    text
);

CREATE TABLE heartbeats (
  at timestamptz PRIMARY KEY DEFAULT now()
);

-- The run log a client can read: one row per lead, with what was sent and how fast.
CREATE VIEW run_log AS
SELECT l.id, l.received_at, l.source, l.is_test, l.name, l.service,
       l.replied_at,
       round(extract(epoch FROM (l.replied_at - l.received_at))::numeric, 1) AS reply_seconds,
       l.reply_attempts,
       (SELECT count(*) FROM messages m WHERE m.lead_id = l.id AND m.kind = 'followup') AS followups_sent,
       l.next_followup_step, l.next_followup_at
FROM leads l;
