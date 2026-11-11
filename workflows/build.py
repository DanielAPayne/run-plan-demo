#!/usr/bin/env python3
"""Build the demo's n8n workflows as JSON files in workflows/out/.

The workflows are written here, not drawn in the editor, so every node is reviewable
in one file and a rebuild gives the same result. Run:  python3 -I workflows/build.py
"""
import json
import os
import uuid

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "out")
NS = uuid.UUID("6f1f0f52-3c0c-4d1e-9b54-7e2f1c9a0001")

PG = {"postgres": {"id": "rdCredPostgres01", "name": "Demo Postgres"}}
SMTP = {"smtp": {"id": "rdCredSmtp000001", "name": "Mailpit SMTP"}}
ALERT_SMTP = {"smtp": {"id": "rdCredAlertSmtp1", "name": "Alert channel SMTP"}}
ERROR_WORKFLOW = "rdErrorAlert0001"
WEBHOOK_URL = "http://localhost:5678/webhook/lead"

BUSINESS = "Example Roofing Co."
FROM = "hello@example-roofing.test"
OPS = "ops@rundemo.test"


class Flow:
    def __init__(self, wid, name, error_workflow=True):
        self.wid, self.name = wid, name
        self.nodes, self.conn = [], {}
        self.x = 0
        self.settings = {"executionOrder": "v1", "timezone": "America/Chicago"}
        if error_workflow:
            self.settings["errorWorkflow"] = ERROR_WORKFLOW

    def node(self, name, type_, version, params, creds=None, y=0, **extra):
        n = {
            "parameters": params,
            "id": str(uuid.uuid5(NS, f"{self.wid}/{name}")),
            "name": name,
            "type": f"n8n-nodes-base.{type_}",
            "typeVersion": version,
            "position": [self.x, y],
        }
        if creds:
            n["credentials"] = creds
        n.update(extra)
        self.nodes.append(n)
        self.x += 220
        return name

    def link(self, a, b, output=0):
        outs = self.conn.setdefault(a, {"main": []})["main"]
        while len(outs) <= output:
            outs.append([])
        outs[output].append({"node": b, "type": "main", "index": 0})

    def chain(self, *names):
        for a, b in zip(names, names[1:]):
            self.link(a, b)

    def dump(self):
        return {
            "id": self.wid,
            "name": self.name,
            "nodes": self.nodes,
            "connections": self.conn,
            "settings": self.settings,
            "active": False,
            "pinData": {},
            "versionId": str(uuid.uuid5(NS, self.wid + "/version")),
        }


def pg(query, param=None):
    opts = {"queryBatching": "independently"}
    if param:
        # One JSON parameter per query. The node passes a JSON string through whole;
        # a plain string would be split on its commas.
        opts["queryReplacement"] = "={{ " + param + " }}"
    return {"operation": "executeQuery", "query": query, "options": opts}


def email(to, subject, text, sender=FROM):
    return {
        "resource": "email",
        "operation": "send",
        "fromEmail": sender,
        "toEmail": to,
        "subject": subject,
        "emailFormat": "text",
        "text": text,
        "options": {"appendAttribution": False},
    }


def if_exists(expr):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": str(uuid.uuid5(NS, expr)),
                "leftValue": expr,
                "rightValue": "",
                "operator": {"type": "number", "operation": "exists", "singleValue": True},
            }],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def if_true(expr):
    return {
        "conditions": {
            "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
            "conditions": [{
                "id": str(uuid.uuid5(NS, expr)),
                "leftValue": expr,
                "rightValue": "",
                "operator": {"type": "boolean", "operation": "true", "singleValue": True},
            }],
            "combinator": "and",
        },
        "looseTypeValidation": True,
        "options": {},
    }


def run_now(f, path, first):
    """A second way in: run the scheduled workflow now. Used for tests and after a fix.
    The demo listens on this Mac only; for a client this door would need a secret header."""
    x = f.x
    f.x = 0
    f.node("Run now", "webhook", 2,
           {"httpMethod": "POST", "path": f"ops/{path}", "responseMode": "onReceived", "options": {}},
           y=220, webhookId=str(uuid.uuid5(NS, f"webhook/ops/{path}")))
    f.x = x
    f.link("Run now", first)


def every_minutes(n):
    return {"rule": {"interval": [{"field": "minutes", "minutesInterval": n}]}}


def cron(expr):
    return {"rule": {"interval": [{"field": "cronExpression", "expression": expr}]}}


# ---------------------------------------------------------------- code nodes

VALIDATE_JS = r"""
// Accept only what the reply needs; say exactly what is wrong otherwise.
const b = $json.body || {};
const clean = (v) => (typeof v === 'string' ? v.trim() : '');
const lead = {
  name: clean(b.name).slice(0, 120),
  email: clean(b.email).toLowerCase().slice(0, 200),
  phone: clean(b.phone).slice(0, 40),
  service: clean(b.service).toLowerCase().slice(0, 80),
  message: clean(b.message).slice(0, 2000),
  source: clean(b.source).slice(0, 40) || 'web',
  is_test: b.is_test === true,
};
const problems = [];
if (!lead.name) problems.push('name is required');
if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(lead.email)) problems.push('a valid email is required');
return { json: { valid: problems.length === 0, problems, lead } };
"""

DRAFT_REPLY_JS = r"""
// The first reply. In this demo it is chosen by rule from the service the lead asked about.
// In a client build, this node is where a language model drafts the reply; everything
// around it (saving first, sending, recording, the checks) stays the same.
const BUSINESS = '__BUSINESS__';
const l = $json;
const first = (l.name || 'there').split(/\s+/)[0];
const service = l.service || '';
let line;
if (service.includes('replace')) {
  line = 'A full replacement starts with a free inspection, so we can give you a written quote and not a guess.';
} else if (service.includes('repair') || service.includes('leak')) {
  line = 'For a repair we can usually have someone look at it within two working days. If water is coming in now, reply URGENT and we will call you today.';
} else if (service.includes('gutter')) {
  line = 'Gutter work is quick to quote: a few photos are often enough.';
} else if (service.includes('inspect')) {
  line = 'An inspection takes about 45 minutes and you get the photos and a written summary.';
} else {
  line = 'Tell us a little more about what you need and we will point you to the right person.';
}
const subject = `We got your message, ${first}`;
const body = [
  `Hi ${first},`,
  '',
  `Thanks for contacting ${BUSINESS}. ${line}`,
  '',
  'You can book a time here: https://example-roofing.test/book',
  '',
  `${BUSINESS}`,
  'Reply STOP and we will not email you again.',
].join('\n');
return { json: { id: l.id, name: l.name, email: l.email, service, is_test: l.is_test === true, subject, body } };
""".replace("__BUSINESS__", BUSINESS)

DRAFT_FOLLOWUP_JS = r"""
// Follow-ups at 1, 3, 7 and 14 days after the lead arrived, until they book or opt out.
const BUSINESS = '__BUSINESS__';
const l = $json;
const first = (l.name || 'there').split(/\s+/)[0];
const step = Number(l.step);
const texts = {
  1: ['Still need a hand with your roof?', 'Just checking you saw our reply yesterday. Booking takes about a minute:'],
  2: ['A quick question', 'Is the work still needed, or has it been sorted? Either answer helps us. If it is still needed, you can book here:'],
  3: ['What an inspection includes', 'In case it is useful: an inspection takes about 45 minutes, and you keep the photos and the written summary whether or not you hire us. Book here:'],
  4: ['Last note from us', 'This is our last message about your enquiry. If the timing is better later, this link will still work:'],
};
const [subject, opening] = texts[step] || texts[4];
const body = [
  `Hi ${first},`,
  '',
  `${opening} https://example-roofing.test/book`,
  '',
  `${BUSINESS}`,
  'Reply STOP and we will not email you again.',
].join('\n');
return { json: { id: l.id, email: l.email, step, subject, body } };
""".replace("__BUSINESS__", BUSINESS)

SIMULATED_LEAD_JS = r"""
// Demo traffic. These people do not exist; the addresses use the reserved .test domain.
const names = ['Maria Alvarez', 'James Okafor', 'Priya Nair', 'Tom Becker', 'Lena Fischer', 'Sam Whitfield',
  'Aisha Rahman', 'Carlos Mendes', 'Nora Lindqvist', 'Ben Hartley', 'Grace Kim', 'Omar Haddad'];
const services = ['roof repair', 'roof repair', 'roof leak', 'roof replacement', 'gutter cleaning', 'roof inspection', 'other'];
const messages = ['Water stain on the bedroom ceiling after the storm.', 'A few shingles came off on the south side.',
  'We are selling the house and need the roof checked.', 'Gutters overflow when it rains hard.',
  'The roof is about 22 years old. What would a new one cost?', 'Can someone come this week?'];
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const name = pick(names);
const tag = Date.now().toString(36);
return [{ json: {
  name,
  email: `${name.toLowerCase().replace(/[^a-z]+/g, '.')}.${tag}@leads.test`,
  phone: '555-01' + String(Math.floor(Math.random() * 100)).padStart(2, '0'),
  service: pick(services),
  message: pick(messages),
  source: 'simulator',
  is_test: false,
} }];
"""

TEST_LEAD_JS = r"""
// The daily test: one clearly marked record through the real front door.
const email = `runplan-test-${Date.now()}@rundemo.test`;
return [{ json: { name: 'Run-plan Test', email, phone: '', service: 'roof repair',
  message: 'Daily test record. Not a customer.', source: 'daily-test', is_test: true } }];
"""

JUDGE_JS = r"""
// Passed only if the record was saved, replied to within two minutes, and the email really arrived.
const sent = $('Make test lead').item.json;
const row = $('Read the lead back').item.json;
const mail = $json;
const replied = row.replied === true;
const seconds = row.reply_seconds === null || row.reply_seconds === undefined ? null : Number(row.reply_seconds);
const delivered = Number(mail.messages_count ?? mail.total ?? 0);
const passed = replied && delivered >= 1 && seconds !== null && seconds <= 120;
return { json: { kind: 'daily-test', passed, detail: { email: sent.email, saved: row.id !== undefined, replied, reply_seconds: seconds, delivered } } };
"""

FAIL_IF_NOT_PASSED_JS = r"""
// A failed test is an error, so it reaches the same alert as any other failure.
if ($json.passed !== true) {
  throw new Error('Daily test failed: ' + JSON.stringify($json.detail));
}
return $input.item;
"""

SUMMARISE_ERROR_JS = r"""
// What failed, where, and which run, in a form that fits one alert line.
const e = $json;
const message = String(e.execution?.error?.message || e.trigger?.error?.message || 'unknown error').slice(0, 500);
return { json: {
  source: 'n8n-error-workflow',
  workflow: e.workflow?.name || '(unknown)',
  node: e.execution?.lastNodeExecuted || '(trigger)',
  message,
  execution_id: String(e.execution?.id ?? ''),
} };
"""

# ---------------------------------------------------------------- queries

SAVE_LEAD_SQL = """INSERT INTO leads (name, email, phone, service, message, source, is_test)
SELECT r.name, r.email, nullif(r.phone, ''), nullif(r.service, ''), nullif(r.message, ''), r.source, coalesce(r.is_test, false)
FROM json_to_record($1::json) AS r(name text, email text, phone text, service text, message text, source text, is_test boolean)
RETURNING id, name, email, service, is_test, received_at;"""

RECORD_REPLY_SQL = """WITH j AS (
  SELECT * FROM json_to_record($1::json) AS r(id bigint, subject text)
), m AS (
  INSERT INTO messages (lead_id, kind, step, subject)
  SELECT id, 'reply', 0, subject FROM j
  RETURNING lead_id, sent_at
)
UPDATE leads l
SET replied_at = m.sent_at,
    next_followup_step = CASE WHEN l.is_test THEN NULL ELSE 1 END,
    next_followup_at   = CASE WHEN l.is_test THEN NULL ELSE l.received_at + interval '1 day' END
FROM m
WHERE l.id = m.lead_id AND l.replied_at IS NULL
RETURNING l.id, round(extract(epoch FROM (l.replied_at - l.received_at))::numeric, 1) AS reply_seconds;"""

UNREPLIED_SQL = """UPDATE leads SET reply_attempts = reply_attempts + 1
WHERE id IN (
  SELECT id FROM leads
  WHERE replied_at IS NULL AND received_at < now() - interval '2 minutes' AND reply_attempts < 10
  ORDER BY id LIMIT 20
)
RETURNING id, name, email, service, is_test;"""

DUE_FOLLOWUPS_SQL = """SELECT id, name, email, service, next_followup_step AS step
FROM leads
WHERE replied_at IS NOT NULL AND booked_at IS NULL AND unsubscribed_at IS NULL AND NOT is_test
  AND next_followup_step IS NOT NULL AND next_followup_at <= now()
ORDER BY next_followup_at
LIMIT 20;"""

RECORD_FOLLOWUP_SQL = """WITH j AS (
  SELECT * FROM json_to_record($1::json) AS r(id bigint, step int, subject text)
), m AS (
  INSERT INTO messages (lead_id, kind, step, subject)
  SELECT id, 'followup', step, subject FROM j
  RETURNING lead_id, step
)
UPDATE leads l
SET next_followup_step = CASE WHEN m.step >= 4 THEN NULL ELSE m.step + 1 END,
    next_followup_at   = CASE WHEN m.step >= 4 THEN NULL
                              ELSE l.received_at + (ARRAY[1, 3, 7, 14])[m.step + 1] * interval '1 day' END
FROM m
WHERE l.id = m.lead_id
RETURNING l.id, l.next_followup_step;"""

READ_BACK_SQL = """SELECT id, (replied_at IS NOT NULL) AS replied,
       round(extract(epoch FROM (replied_at - received_at))::numeric, 1) AS reply_seconds
FROM leads
WHERE email = (SELECT r.email FROM json_to_record($1::json) AS r(email text))
ORDER BY id DESC LIMIT 1;"""

RECORD_CHECK_SQL = """INSERT INTO checks (kind, passed, detail)
SELECT r.kind, r.passed, r.detail FROM json_to_record($1::json) AS r(kind text, passed boolean, detail jsonb)
RETURNING id, passed, detail;"""

RECORD_INCIDENT_SQL = """WITH j AS (
  SELECT * FROM json_to_record($1::json) AS r(source text, workflow text, node text, message text, execution_id text)
), again AS (
  -- The same step failing again while its incident is open: count it, don't open another.
  UPDATE incidents i
  SET occurrences = i.occurrences + 1, last_seen_at = now(), execution_id = j.execution_id
  FROM j
  WHERE i.source = j.source AND i.workflow = j.workflow AND i.node = j.node AND i.resolved_at IS NULL
  RETURNING i.id, i.opened_at, i.workflow, i.node, i.message, i.execution_id, i.occurrences
), fresh AS (
  INSERT INTO incidents (source, workflow, node, message, execution_id, last_seen_at)
  SELECT source, workflow, node, message, execution_id, now() FROM j
  WHERE NOT EXISTS (SELECT 1 FROM again)
  RETURNING id, opened_at, workflow, node, message, execution_id, occurrences
)
SELECT * FROM again UNION ALL SELECT * FROM fresh;"""

# ---------------------------------------------------------------- workflows


def reply_tail(f, first):
    """Draft, send and record the first reply. Shared by the intake and the retry."""
    f.node("Draft reply", "code", 2, {"mode": "runOnceForEachItem", "jsCode": DRAFT_REPLY_JS})
    f.node("Send reply", "emailSend", 2.1,
           email("={{ $json.email }}", "={{ $json.subject }}", "={{ $json.body }}"), SMTP)
    f.node("Record reply", "postgres", 2.6,
           pg(RECORD_REPLY_SQL,
              "JSON.stringify({ id: $('Draft reply').item.json.id, subject: $('Draft reply').item.json.subject })"), PG)
    f.chain(first, "Draft reply", "Send reply", "Record reply")


def intake():
    f = Flow("rdIntake00000001", "1. New lead: save, reply, start follow-ups")
    f.node("New lead", "webhook", 2,
           {"httpMethod": "POST", "path": "lead", "responseMode": "responseNode", "options": {}},
           webhookId=str(uuid.uuid5(NS, "webhook/lead")))
    f.node("Validate", "code", 2, {"mode": "runOnceForEachItem", "jsCode": VALIDATE_JS})
    f.node("Valid?", "if", 2.2, if_true("={{ $json.valid }}"))
    f.node("Save lead", "postgres", 2.6, pg(SAVE_LEAD_SQL, "JSON.stringify($json.lead)"), PG)
    # Answer the form as soon as the lead is safe in the database; the reply follows.
    f.node("Answer the form", "respondToWebhook", 1.1,
           {"respondWith": "json", "responseBody": "={{ JSON.stringify({ ok: true, id: $json.id }) }}", "options": {"responseCode": 200}})
    f.chain("New lead", "Validate", "Valid?")
    f.link("Valid?", "Save lead", 0)
    f.chain("Save lead", "Answer the form")
    reply_tail(f, "Answer the form")
    f.x = 660
    f.node("Refuse", "respondToWebhook", 1.1,
           {"respondWith": "json", "responseBody": "={{ JSON.stringify({ ok: false, problems: $json.problems }) }}", "options": {"responseCode": 400}},
           y=220)
    f.link("Valid?", "Refuse", 1)
    return f


def retry():
    f = Flow("rdRetry000000001", "2. Retry: reply to any lead that is still waiting")
    f.node("Every 5 minutes", "scheduleTrigger", 1.2, every_minutes(5))
    f.node("Leads still waiting", "postgres", 2.6, pg(UNREPLIED_SQL), PG)
    f.node("Any?", "if", 2.2, if_exists("={{ $json.id }}"))
    f.chain("Every 5 minutes", "Leads still waiting", "Any?")
    reply_tail(f, "Any?")
    run_now(f, "retry", "Leads still waiting")
    return f


def followups():
    f = Flow("rdFollowups00001", "3. Follow-ups: days 1, 3, 7 and 14")
    f.node("Every 10 minutes", "scheduleTrigger", 1.2, every_minutes(10))
    f.node("Follow-ups due", "postgres", 2.6, pg(DUE_FOLLOWUPS_SQL), PG)
    f.node("Any?", "if", 2.2, if_exists("={{ $json.id }}"))
    f.node("Draft follow-up", "code", 2, {"mode": "runOnceForEachItem", "jsCode": DRAFT_FOLLOWUP_JS})
    f.node("Send follow-up", "emailSend", 2.1,
           email("={{ $json.email }}", "={{ $json.subject }}", "={{ $json.body }}"), SMTP)
    f.node("Record follow-up", "postgres", 2.6,
           pg(RECORD_FOLLOWUP_SQL,
              "JSON.stringify({ id: $('Draft follow-up').item.json.id, step: $('Draft follow-up').item.json.step, subject: $('Draft follow-up').item.json.subject })"), PG)
    f.chain("Every 10 minutes", "Follow-ups due", "Any?", "Draft follow-up", "Send follow-up", "Record follow-up")
    run_now(f, "followups", "Follow-ups due")
    return f


def daily_test():
    f = Flow("rdDailyTest00001", "4. Daily test: one marked record through the whole flow")
    f.node("Every day at 09:05", "scheduleTrigger", 1.2, cron("5 9 * * *"))
    f.node("Make test lead", "code", 2, {"jsCode": TEST_LEAD_JS})
    f.node("Send it to the front door", "httpRequest", 4.2,
           {"method": "POST", "url": WEBHOOK_URL, "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json) }}", "options": {"timeout": 15000}})
    f.node("Wait 10 seconds", "wait", 1.1, {"amount": 10, "unit": "seconds"},
           webhookId=str(uuid.uuid5(NS, "wait/daily-test")))
    f.node("Read the lead back", "postgres", 2.6,
           pg(READ_BACK_SQL, "JSON.stringify({ email: $('Make test lead').item.json.email })"), PG)
    f.node("Did the email arrive?", "httpRequest", 4.2,
           {"method": "GET", "url": "http://mailpit:8025/api/v1/search", "sendQuery": True,
            "queryParameters": {"parameters": [
                {"name": "query", "value": "={{ 'to:' + $('Make test lead').item.json.email }}"}]},
            "options": {"timeout": 15000}})
    f.node("Judge", "code", 2, {"mode": "runOnceForEachItem", "jsCode": JUDGE_JS})
    f.node("Record the result", "postgres", 2.6, pg(RECORD_CHECK_SQL, "JSON.stringify($json)"), PG)
    f.node("Fail if not passed", "code", 2, {"mode": "runOnceForEachItem", "jsCode": FAIL_IF_NOT_PASSED_JS})
    f.chain("Every day at 09:05", "Make test lead", "Send it to the front door", "Wait 10 seconds",
            "Read the lead back", "Did the email arrive?", "Judge", "Record the result", "Fail if not passed")
    run_now(f, "daily-test", "Make test lead")
    return f


def heartbeat():
    f = Flow("rdHeartbeat00001", "5. Heartbeat: every 5 minutes")
    f.node("Every 5 minutes", "scheduleTrigger", 1.2, every_minutes(5))
    f.node("Write heartbeat", "postgres", 2.6,
           pg("INSERT INTO heartbeats (at) VALUES (now()) ON CONFLICT DO NOTHING RETURNING at;"), PG)
    f.chain("Every 5 minutes", "Write heartbeat")
    run_now(f, "heartbeat", "Write heartbeat")
    return f


def error_alert():
    f = Flow(ERROR_WORKFLOW, "6. On any failure: record an incident, then alert", error_workflow=False)
    f.node("A workflow failed", "errorTrigger", 1, {})
    f.node("Summarise", "code", 2, {"mode": "runOnceForEachItem", "jsCode": SUMMARISE_ERROR_JS})
    # The incident is written first, so it exists even if the alert itself cannot be sent.
    f.node("Record incident", "postgres", 2.6, pg(RECORD_INCIDENT_SQL, "JSON.stringify($json)"), PG)
    # One alert per incident. Repeats are counted on the incident and shown in the report.
    f.node("First time?", "if", 2.2, if_true("={{ $json.occurrences == 1 }}"))
    f.node("Alert the operator", "emailSend", 2.1,
           email(OPS, "=ALERT: {{ $json.workflow }} failed at {{ $json.node }}",
                 "=Incident {{ $json.id }}, opened {{ $json.opened_at }}\n\nWorkflow: {{ $json.workflow }}\nNode: {{ $json.node }}\nError: {{ $json.message }}\nExecution: {{ $json.execution_id }}\n",
                 sender="alerts@rundemo.test"),
           ALERT_SMTP, onError="continueRegularOutput")
    f.chain("A workflow failed", "Summarise", "Record incident", "First time?", "Alert the operator")
    return f


def simulator():
    f = Flow("rdSimulator00001", "7. Demo only: a synthetic lead every two hours, 08:17 to 20:17")
    f.node("Every two hours", "scheduleTrigger", 1.2, cron("17 8-20/2 * * *"))
    f.node("Invent a lead", "code", 2, {"jsCode": SIMULATED_LEAD_JS})
    f.node("Send it to the front door", "httpRequest", 4.2,
           {"method": "POST", "url": WEBHOOK_URL, "sendBody": True, "specifyBody": "json",
            "jsonBody": "={{ JSON.stringify($json) }}", "options": {"timeout": 15000}})
    f.chain("Every two hours", "Invent a lead", "Send it to the front door")
    run_now(f, "simulate", "Invent a lead")
    return f


def main():
    os.makedirs(OUT, exist_ok=True)
    for old in os.listdir(OUT):
        if old.endswith(".json"):
            os.remove(os.path.join(OUT, old))
    flows = [error_alert(), intake(), retry(), followups(), daily_test(), heartbeat(), simulator()]
    for f in flows:
        with open(os.path.join(OUT, f"{f.wid}.json"), "w") as fh:
            json.dump(f.dump(), fh, indent=2)
            fh.write("\n")
        print(f"{f.wid}  {len(f.nodes):2d} nodes  {f.name}")


if __name__ == "__main__":
    main()
