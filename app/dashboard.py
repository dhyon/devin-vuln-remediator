from __future__ import annotations

from html import escape
from typing import Any

from app.metrics import build_metrics
from app.models import RemediationJob


def render_dashboard(
    jobs: list[RemediationJob],
    events: list[dict[str, Any]] | None = None,
    demo_mode: bool = False,
    engineer_hours_per_remediation: float = 2.0,
    engineer_hourly_cost: float = 150.0,
) -> str:
    metrics = build_metrics(jobs, engineer_hours_per_remediation, engineer_hourly_cost)
    events = events or []
    cards = [
        ("Total findings", str(metrics.total_jobs)),
        ("Active Devin sessions", str(metrics.active_jobs)),
        ("Completed remediations", str(metrics.completed_jobs)),
        ("PRs opened", str(metrics.pr_created_jobs)),
        ("Success rate", pct(metrics.success_rate)),
        ("Median time to PR", duration(metrics.median_time_to_pr_seconds)),
        ("Average time to completion", duration(metrics.average_time_to_completion_seconds)),
        ("Total ACUs consumed", f"{metrics.total_acus_consumed:.1f}"),
    ]
    card_html = "\n".join(
        f'<div class="card"><div class="label">{escape(label)}</div><div class="value">{escape(value)}</div></div>'
        for label, value in cards
    )
    rows = "\n".join(render_job_row(job) for job in jobs) or '<tr><td colspan="10">No jobs yet.</td></tr>'
    event_rows = "\n".join(render_event_row(event) for event in events) or '<tr><td colspan="5">No events recorded yet.</td></tr>'
    demo_controls = ""
    if demo_mode:
        demo_controls = """
        <section>
          <h2>Demo controls</h2>
          <pre>curl -X POST http://localhost:8000/demo/seed
curl -X POST http://localhost:8000/demo/simulate-webhook
curl -X POST http://localhost:8000/poll</pre>
        </section>
        """

    return f"""<!doctype html>
<html>
<head>
  <title>Devin Vulnerability Remediation Control Plane</title>
  <style>
    :root {{ color-scheme: light; }}
    body {{ margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; background: #f6f7f9; color: #172033; }}
    header {{ background: #fff; border-bottom: 1px solid #dde3ea; padding: 24px 32px; }}
    main {{ padding: 24px 32px 40px; }}
    h1 {{ margin: 0; font-size: 26px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 28px 0 12px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .card, .panel {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 14px; }}
    .label {{ color: #64748b; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
    .value {{ font-size: 24px; font-weight: 700; margin-top: 7px; }}
    .impact {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
    table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #dde3ea; }}
    th, td {{ padding: 10px 11px; border-bottom: 1px solid #edf1f5; text-align: left; vertical-align: top; font-size: 13px; }}
    th {{ background: #eef3f8; color: #334155; font-weight: 650; }}
    a {{ color: #075985; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .pill {{ display: inline-block; padding: 3px 8px; border-radius: 999px; background: #e8f2ff; color: #075985; white-space: nowrap; }}
    pre {{ background: #111827; color: #f8fafc; padding: 14px; border-radius: 8px; overflow-x: auto; }}
  </style>
</head>
<body>
  <header>
    <h1>Devin Vulnerability Remediation Control Plane</h1>
  </header>
  <main>
    <section class="grid">{card_html}</section>

    <section>
      <h2>Business impact</h2>
      <div class="impact">
        <div class="panel"><div class="label">Engineer hours avoided</div><div class="value">{metrics.engineer_hours_avoided:.1f}</div></div>
        <div class="panel"><div class="label">Estimated cost avoided</div><div class="value">${metrics.estimated_cost_avoided:,.0f}</div></div>
        <div class="panel"><div class="label">Backlog reduction</div><div class="value">{metrics.backlog_reduction_percentage:.1f}%</div></div>
        <div class="panel"><div class="label">Average remediation cycle time</div><div class="value">{duration(metrics.average_remediation_cycle_time_seconds)}</div></div>
      </div>
    </section>

    <section>
      <h2>Jobs</h2>
      <table>
        <thead>
          <tr><th>Issue</th><th>Title</th><th>Status</th><th>Devin session</th><th>PR</th><th>ACUs</th><th>Time to PR</th><th>Time to completion</th><th>Last updated</th><th>Failure reason</th></tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </section>

    <section>
      <h2>Recent events</h2>
      <table>
        <thead><tr><th>Time</th><th>Issue</th><th>Type</th><th>Message</th><th>Payload</th></tr></thead>
        <tbody>{event_rows}</tbody>
      </table>
    </section>

    {demo_controls}
  </main>
</body>
</html>"""


def render_job_row(job: RemediationJob) -> str:
    issue = link(job.issue_url, f"#{job.issue_number}") if job.issue_url else f"#{job.issue_number}"
    session = link(job.devin_session_url, "session") if job.devin_session_url else "-"
    pr = link(job.pr_url, "PR") if job.pr_url else "-"
    return f"""
    <tr>
      <td>{issue}<br><small>{escape(job.repository)}</small></td>
      <td>{escape(job.issue_title)}</td>
      <td><span class="pill">{escape(job.status.value)}</span></td>
      <td>{session}</td>
      <td>{pr}</td>
      <td>{job.acus_consumed:.2f}</td>
      <td>{duration(seconds_between(job.created_at, job.pr_opened_at))}</td>
      <td>{duration(seconds_between(job.created_at, job.completed_at))}</td>
      <td>{escape(job.updated_at.strftime("%Y-%m-%d %H:%M"))}</td>
      <td>{escape(job.failure_reason or "-")}</td>
    </tr>
    """


def render_event_row(event: dict[str, Any]) -> str:
    issue = "-"
    if event.get("repository") and event.get("issue_number"):
        issue = f"{escape(str(event['repository']))}#{escape(str(event['issue_number']))}"
    return f"""
    <tr>
      <td>{escape(str(event.get("created_at") or "-"))}</td>
      <td>{issue}</td>
      <td>{escape(str(event.get("event_type") or "-"))}</td>
      <td>{escape(str(event.get("message") or ""))}</td>
      <td>{escape(str(event.get("payload_json") or "{}"))}</td>
    </tr>
    """


def link(url: str | None, label: str) -> str:
    if not url:
        return "-"
    return f'<a href="{escape(url)}" target="_blank" rel="noreferrer">{escape(label)}</a>'


def seconds_between(start, end) -> float | None:
    if not start or not end:
        return None
    return (end - start).total_seconds()


def duration(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        return f"{seconds / 60:.1f}m"
    return f"{seconds / 3600:.1f}h"


def pct(value: float) -> str:
    return f"{value:.0%}"
