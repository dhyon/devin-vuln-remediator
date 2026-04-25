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
        ("Total findings", str(metrics.total_jobs), "All security findings currently tracked by the control plane."),
        ("Open remediation jobs", str(metrics.active_jobs), "Jobs still in the remediation workflow, including queued, running, PR-opened, and waiting states."),
        ("Active Devin sessions", str(metrics.active_devin_sessions), "Jobs with Devin sessions that are started, running, or waiting for user or approval input."),
        ("Completed jobs (PRs Merged)", str(metrics.completed_jobs), "Jobs Devin has finished successfully."),
        ("PRs opened", str(metrics.pr_created_jobs), "Tracked jobs where Devin has opened a remediation pull request."),
        ("Completion rate", pct(metrics.completion_rate), "Completed remediation jobs divided by all tracked findings."),
        ("Terminal success rate", pct(metrics.success_rate), "Completed jobs divided by jobs that reached either completed or failed."),
        ("Median time to PR", duration(metrics.median_time_to_pr_seconds), "The middle time from job creation to Devin opening a pull request."),
        ("Average time to completion", duration(metrics.average_time_to_completion_seconds), "Average time from job creation until jobs reached completed or failed."),
        ("Total ACUs consumed", f"{metrics.total_acus_consumed:.1f}", "Total Agent Compute Units reported across tracked Devin sessions."),
    ]
    card_html = "\n".join(render_metric_box("card", label, value, description) for label, value, description in cards)
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
    header {{ display: flex; align-items: center; justify-content: space-between; gap: 16px; background: #fff; border-bottom: 1px solid #dde3ea; padding: 24px 32px; }}
    main {{ padding: 24px 32px 40px; }}
    h1 {{ margin: 0; font-size: 26px; letter-spacing: 0; }}
    h2 {{ font-size: 18px; margin: 28px 0 12px; }}
    .dashboard-actions {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
    .poll-button {{ border: 1px solid #075985; border-radius: 6px; background: #075985; color: #fff; cursor: pointer; font: inherit; font-size: 13px; font-weight: 650; padding: 8px 12px; }}
    .poll-button:hover:not(:disabled) {{ background: #0c4a6e; }}
    .poll-button:disabled {{ cursor: wait; opacity: .7; }}
    .poll-status {{ color: #64748b; font-size: 13px; min-height: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 12px; }}
    .card, .panel {{ background: #fff; border: 1px solid #dde3ea; border-radius: 8px; padding: 14px; }}
    .metric-box {{ position: relative; outline: none; }}
    .metric-box:hover,
    .metric-box:focus-within {{ z-index: 10; }}
    .metric-box:focus-visible {{ border-color: #075985; box-shadow: 0 0 0 3px rgba(7, 89, 133, .14); }}
    .metric-heading {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
    .metric-help {{
      position: relative;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 auto;
      width: 18px;
      height: 18px;
      border: 1px solid #cbd5e1;
      border-radius: 999px;
      background: #f8fafc;
      color: #475569;
      font-size: 12px;
      font-weight: 700;
      line-height: 1;
      cursor: help;
    }}
    .metric-help:focus {{ outline: none; }}
    .metric-help:focus-visible {{ border-color: #075985; box-shadow: 0 0 0 3px rgba(7, 89, 133, .14); }}
    .metric-tooltip {{
      position: absolute;
      right: -2px;
      bottom: calc(100% + 9px);
      width: min(260px, 72vw);
      z-index: 20;
      pointer-events: none;
      opacity: 0;
      visibility: hidden;
      transform: translateY(3px);
      transition: opacity .14s ease, transform .14s ease;
      background: #172033;
      color: #fff;
      border-radius: 6px;
      padding: 9px 10px;
      font-size: 12px;
      font-weight: 500;
      line-height: 1.35;
      letter-spacing: 0;
      text-transform: none;
      box-shadow: 0 10px 24px rgba(15, 23, 42, .16);
    }}
    .metric-help:hover .metric-tooltip,
    .metric-help:focus-visible .metric-tooltip {{
      opacity: 1;
      visibility: visible;
      transform: translateY(0);
    }}
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
    <div class="dashboard-actions">
      <button class="poll-button" id="poll-now" type="button">Poll Status Now</button>
      <span class="poll-status" id="poll-status" aria-live="polite"></span>
    </div>
  </header>
  <main>
    <section class="grid">{card_html}</section>

    <section>
      <h2>Business impact</h2>
      <div class="impact">
        {render_metric_box("panel", "Engineer hours avoided", f"{metrics.engineer_hours_avoided:.1f}", "Completed remediations multiplied by the configured engineer-hours estimate per remediation.")}
        {render_metric_box("panel", "Estimated cost avoided", f"${metrics.estimated_cost_avoided:,.0f}", "Engineer hours avoided multiplied by the configured hourly engineering cost.")}
        {render_metric_box("panel", "Backlog reduction", f"{metrics.backlog_reduction_percentage:.1f}%", "Completed remediations as a percentage of all tracked findings.")}
        {render_metric_box("panel", "Average remediation cycle time", duration(metrics.average_remediation_cycle_time_seconds), "Average time from job creation until tracked jobs reached completed or failed.")}
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
  <script>
    const pollNowButton = document.getElementById("poll-now");
    const pollStatus = document.getElementById("poll-status");

    pollNowButton.addEventListener("click", async () => {{
      pollNowButton.disabled = true;
      pollStatus.textContent = "Polling...";

      try {{
        const response = await fetch("/poll", {{ method: "POST" }});
        if (!response.ok) {{
          throw new Error(`Poll failed with status ${{response.status}}`);
        }}
        const result = await response.json();
        pollStatus.textContent = `Updated ${{result.updated}} job(s). Refreshing...`;
        window.location.reload();
      }} catch (error) {{
        pollStatus.textContent = "Poll failed.";
        pollNowButton.disabled = false;
      }}
    }});
  </script>
</body>
</html>"""


def render_metric_box(class_name: str, label: str, value: str, description: str) -> str:
    return (
        f'<div class="{escape(class_name)} metric-box" tabindex="0" '
        f'aria-label="{escape(label)}: {escape(value)}. {escape(description)}" '
        f'data-description="{escape(description)}">'
        f'<div class="metric-heading"><div class="label">{escape(label)}</div>'
        f'<span class="metric-help" tabindex="0" aria-label="{escape(description)}" title="{escape(description)}">?'
        f'<span class="metric-tooltip" role="tooltip">{escape(description)}</span></span></div>'
        f'<div class="value">{escape(value)}</div></div>'
    )


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
