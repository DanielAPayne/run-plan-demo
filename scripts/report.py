#!/usr/bin/env python3
"""Write the run report from the system's own records.

Every figure comes from the database: the automation's tables (leads, messages, checks,
incidents, heartbeats) and n8n's own execution table. Nothing is typed in by hand.

  python3 -I scripts/report.py                 # everything recorded so far
  python3 -I scripts/report.py --days 30       # the last 30 days
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REAL = "('web', 'simulator')"          # what counts as a lead; tests, drills and setup records are listed apart


def q(db, sql):
    """Run a query in the Postgres container and return its rows as dicts."""
    wrapped = f"SELECT coalesce(json_agg(t), '[]'::json) FROM ({sql}) t"
    r = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "postgres", "-d", db,
         "-X", "-q", "-At", "-v", "ON_ERROR_STOP=1", "-c", wrapped],
        cwd=HERE, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        sys.exit(f"query failed: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def one(db, sql):
    rows = q(db, sql)
    return rows[0] if rows else {}


def dur(seconds):
    if float(seconds or 0) < 10:
        return f"{float(seconds or 0):.1f} s"
    seconds = int(round(float(seconds or 0)))
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 5400:
        return f"{seconds // 60} min {seconds % 60:02d} s"
    return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, help="cover the last N days (default: everything recorded)")
    ap.add_argument("--out", help="output file (default: reports/REPORT_<to-date>.md)")
    a = ap.parse_args()

    span = one("demo", "SELECT min(at) AS first, now() AS now FROM heartbeats")
    if not span.get("first"):
        sys.exit("no heartbeats recorded yet")
    # The period starts at the first thing ever recorded, so nothing from the first minutes is left out.
    first = ("(SELECT least((SELECT min(at) FROM heartbeats), (SELECT min(received_at) FROM leads), "
             "(SELECT min(opened_at) FROM incidents)))")
    start = first if not a.days else f"greatest({first}, now() - interval '{a.days} days')"
    p = one("demo", f"SELECT to_char({start}, 'YYYY-MM-DD HH24:MI') AS from_, to_char(now(), 'YYYY-MM-DD HH24:MI') AS to_, "
                    f"extract(epoch FROM now() - {start}) AS seconds, to_char({start}, 'YYYY-MM-DD\"T\"HH24:MI:SSOF') AS from_iso")
    since = f"'{p['from_iso']}'::timestamptz"

    leads = one("demo", f"""
        SELECT count(*) AS received,
               count(*) FILTER (WHERE reply_seconds <= 120) AS on_time,
               count(*) FILTER (WHERE reply_seconds > 120) AS late,
               count(*) FILTER (WHERE replied_at IS NULL) AS waiting,
               coalesce(max(reply_seconds), 0) AS slowest,
               coalesce(percentile_cont(0.5) WITHIN GROUP (ORDER BY reply_seconds), 0) AS median
        FROM run_log WHERE source IN {REAL} AND received_at >= {since}""")
    other = q("demo", f"""
        SELECT source, count(*) AS n, count(replied_at) AS replied, coalesce(max(reply_seconds), 0) AS slowest
        FROM run_log WHERE source NOT IN {REAL} AND received_at >= {since} GROUP BY 1 ORDER BY 1""")
    followups = one("demo", f"""
        SELECT count(*) AS n FROM messages m JOIN leads l ON l.id = m.lead_id
        WHERE m.kind = 'followup' AND m.sent_at >= {since} AND l.source IN {REAL}""")
    checks = one("demo", f"SELECT count(*) AS n, count(*) FILTER (WHERE passed) AS passed FROM checks WHERE kind = 'daily-test' AND at >= {since}")
    hb = one("demo", f"""
        SELECT count(*) AS n,
               coalesce(max(gap), 0) AS max_gap,
               count(*) FILTER (WHERE gap > 420) AS gaps
        FROM (SELECT extract(epoch FROM at - lag(at) OVER (ORDER BY at)) AS gap FROM heartbeats WHERE at >= {since}) s""")
    incidents = q("demo", f"""
        SELECT id, to_char(opened_at, 'MM-DD HH24:MI:SS') AS opened, source, workflow, node, message, occurrences, is_drill,
               extract(epoch FROM resolved_at - opened_at) AS open_seconds, resolved_at IS NOT NULL AS closed, resolution
        FROM incidents WHERE opened_at >= {since} ORDER BY opened_at""")
    runs = q("n8n", f"""
        SELECT w.name, count(*) AS runs, count(*) FILTER (WHERE e.status = 'success') AS ok,
               count(*) FILTER (WHERE e.status <> 'success') AS failed
        FROM execution_entity e JOIN workflow_entity w ON w.id = e."workflowId"
        WHERE e."startedAt" >= {since} GROUP BY 1 ORDER BY 1""")

    total_runs = sum(r["runs"] for r in runs)
    failed_runs = sum(r["failed"] for r in runs)
    expected_hb = max(1, int(float(p["seconds"]) // 300))
    real_inc = [i for i in incidents if not i["is_drill"]]
    drills = [i for i in incidents if i["is_drill"]]
    open_inc = [i for i in incidents if not i["closed"]]

    L = []
    w = L.append
    w("# Run report")
    w("")
    w("**Automation:** new-lead reply and 14-day follow-up (demo)")
    w(f"**Period:** {p['from_']} to {p['to_']} (America/Chicago), {dur(p['seconds'])}")
    w(f"**Written:** {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} by `scripts/report.py`, from the system's own records")
    w("")
    w("**What is real here and what is not.** This is a demonstration system. The leads are synthetic: a simulator sends "
      "invented people with `.test` addresses, and the \"email service\" is a local inbox. Everything measured about the "
      "system is real: each run, reply time, test, failure and fix below was recorded as it happened.")
    w("")
    w("## The period in one paragraph")
    w("")
    para = [f"The automation received {leads['received']} lead{'s' if leads['received'] != 1 else ''}."]
    if leads["received"]:
        para.append(f"{leads['on_time']} got a reply within two minutes"
                    + (f", {leads['late']} got one late" if leads["late"] else "")
                    + (f", and {leads['waiting']} {'is' if leads['waiting'] == 1 else 'are'} still waiting" if leads["waiting"] else "") + ".")
    para.append(f"It ran {total_runs:,} times, and {failed_runs} of those runs failed.")
    if real_inc:
        para.append(f"There {'was' if len(real_inc) == 1 else 'were'} {len(real_inc)} real incident{'s' if len(real_inc) != 1 else ''}"
                    + (f" and {len(drills)} from a planned drill" if drills else "") + "; all are listed below.")
    elif drills:
        para.append(f"The only failures were the {len(drills)} incidents of a planned drill.")
    if open_inc:
        para.append(f"**{len(open_inc)} incident{'s are' if len(open_inc) != 1 else ' is'} still open.**")
    w(" ".join(para))
    w("")
    w("## What it did")
    w("")
    w("| Measure | Count |")
    w("|---|---:|")
    w(f"| Leads received | {leads['received']} |")
    w(f"| Replied to within 2 minutes | {leads['on_time']} |")
    w(f"| Replied to late | {leads['late']} |")
    w(f"| Not yet replied to | {leads['waiting']} |")
    w(f"| Follow-up messages sent | {followups['n']} |")
    if leads["received"]:
        w(f"| Typical reply time (median) | {dur(leads['median'])} |")
        w(f"| Slowest reply | {dur(leads['slowest'])} |")
    w("")
    if other:
        w("Records that are not leads, kept apart from the counts above:")
        w("")
        w("| Kind | Records | Replied to | Slowest reply |")
        w("|---|---:|---:|---:|")
        names = {"daily-test": "Daily test records", "drill": "Drill records", "setup-test": "Setup test records"}
        for o in other:
            w(f"| {names.get(o['source'], o['source'])} | {o['n']} | {o['replied']} | {dur(o['slowest'])} |")
        w("")
    w("## Was it running?")
    w("")
    w("| Check | Result |")
    w("|---|---|")
    w(f"| Runs | {total_runs:,}, of which {total_runs - failed_runs:,} succeeded and {failed_runs} failed |")
    w(f"| Daily test | {checks['passed']} passed of {checks['n']} run |")
    w(f"| Heartbeat | {hb['n']:,} recorded of about {expected_hb:,} expected (one every 5 minutes); "
      f"longest gap {dur(hb['max_gap'])}; {hb['gaps']} gap{'s' if hb['gaps'] != 1 else ''} over 7 minutes |")
    w(f"| Incidents | {len(real_inc)} real, {len(drills)} from drills, {len(open_inc)} still open |")
    w("")
    w("| Workflow | Runs | Succeeded | Failed |")
    w("|---|---:|---:|---:|")
    for r in runs:
        w(f"| {r['name']} | {r['runs']:,} | {r['ok']:,} | {r['failed']} |")
    w("")
    w("## Failures and fixes")
    w("")
    if not incidents:
        w("None in this period.")
    else:
        caught = {"n8n-error-workflow": "The failing run raised an alert", "watchdog": "The watchdog, from outside n8n",
                  "operator": "Found on review"}
        w("| # | Opened | What happened | How it was caught | Times | Open for | What fixed it |")
        w("|---:|---|---|---|---:|---|---|")
        for i in incidents:
            what = f"{'**Drill.** ' if i['is_drill'] else ''}{i['workflow']}, at \"{i['node']}\": {i['message']}".replace("|", "/")
            fix = (i["resolution"] or "").replace("|", "/") if i["closed"] else "**Still open**"
            w(f"| {i['id']} | {i['opened']} | {what} | {caught.get(i['source'], i['source'])} | {i['occurrences']} | "
              f"{dur(i['open_seconds']) if i['closed'] else 'open'} | {fix} |")
    w("")
    w("## How to check any number here")
    w("")
    w("- **Each lead:** the `run_log` view in the `demo` database: when it arrived, when it was replied to, and what was sent.")
    w("- **Each run:** n8n's Executions list at http://localhost:5678, or its `execution_entity` table.")
    w("- **Each email:** the inbox at http://localhost:8025. **Each alert:** http://localhost:8026.")
    w("")

    out = a.out or os.path.join(HERE, "reports", f"REPORT_{p['to_'][:10]}.md")
    with open(out, "w") as f:
        f.write("\n".join(L))
    print(out)


if __name__ == "__main__":
    main()
