#!/usr/bin/env python3

import argparse
import html
import json
import os
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Any


SUCCESSFUL_WORKFLOW_RESULTS = {"success", "skipped"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a consolidated Wodby boilerplate update report email.")
    parser.add_argument("report_dir", help="Directory containing boilerplate-update-report.json.")
    parser.add_argument("--run-url", default="", help="GitHub Actions run URL.")
    parser.add_argument("--event", default="", help="GitHub Actions event name.")
    parser.add_argument("--sha", default="", help="Git commit SHA.")
    parser.add_argument("--workflow-result", default="", help="Aggregated update job result.")
    parser.add_argument("--artifact-result", default="", help="Report artifact download step result.")
    return parser.parse_args()


def load_report(report_dir: Path) -> dict[str, Any]:
    return json.loads((report_dir / "boilerplate-update-report.json").read_text())


def workflow_result_failed(workflow_result: str) -> bool:
    parts = [part.strip() for part in workflow_result.split(",") if part.strip()]
    return any(part.rsplit("=", 1)[-1].strip().lower() not in SUCCESSFUL_WORKFLOW_RESULTS for part in parts)


def artifact_result_failed(artifact_result: str) -> bool:
    result = artifact_result.strip().lower()
    return bool(result and result not in SUCCESSFUL_WORKFLOW_RESULTS)


def event_counts(report: dict[str, Any], workflow_result: str, artifact_result: str) -> dict[str, int]:
    totals = report.get("totals") or {}
    return {
        "workflow_failures": 1 if workflow_result_failed(workflow_result) else 0,
        "artifact_failures": 1 if artifact_result_failed(artifact_result) else 0,
        "commits": int(totals.get("commits") or 0),
        "validated": int(totals.get("validated") or 0),
        "failures": int(totals.get("failures") or 0),
        "other_events": int(totals.get("other_events") or 0),
        "report_warnings": int(totals.get("warnings") or 0),
    }


def has_email_worthy_events(counts: dict[str, int]) -> bool:
    return any(value > 0 for value in counts.values())


def append_events(lines: list[str], title: str, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    lines.extend((title, ""))
    for event in events:
        event_type = str(event.get("type") or "event").replace("_", " ")
        lines.append(f"- {event.get('repo') or 'unknown'}: {event_type}: {event.get('message') or ''}")
    lines.append("")


def build_body(
    report: dict[str, Any],
    counts: dict[str, int],
    *,
    run_url: str,
    event: str,
    sha: str,
    workflow_result: str,
    artifact_result: str,
) -> str:
    lines = [
        "Wodby boilerplate update report events were detected.",
        "",
        f"Run: {run_url or 'unknown'}",
        f"Event: {event or 'unknown'}",
        f"Commit: {sha or 'unknown'}",
        f"Update job result: {workflow_result or 'unknown'}",
        f"Artifact download result: {artifact_result or 'unknown'}",
        f"Report date: {report.get('generated_at') or 'unknown'}",
        "",
        "Summary:",
    ]
    lines.extend(f"- {key.replace('_', ' ')}: {value}" for key, value in counts.items())
    lines.append("")

    if counts["workflow_failures"]:
        lines.extend(
            (
                "Workflow Failure",
                "",
                "One or more update jobs did not complete successfully. Check the run URL above.",
                "",
            )
        )
    if counts["artifact_failures"]:
        lines.extend(
            (
                "Report Artifact Failure",
                "",
                "Update report artifacts could not be downloaded. Check the workflow run logs.",
                "",
            )
        )

    append_events(lines, "Dependency Update Commits", report.get("commits") or [])
    append_events(lines, "Validated Dry-run Updates", report.get("validated") or [])
    append_events(lines, "Failures", report.get("failures") or [])
    append_events(lines, "Other Events", report.get("other_events") or [])
    if report.get("warnings"):
        lines.extend(("Report Warnings", ""))
        lines.extend(f"- {warning}" for warning in report["warnings"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def html_event_section(title: str, events: list[dict[str, Any]]) -> str:
    if not events:
        return ""
    rows = "".join(
        "<li>"
        f"<code>{html.escape(str(event.get('repo') or 'unknown'))}</code>: "
        f"{html.escape(str(event.get('type') or 'event').replace('_', ' '))}: "
        f"{html.escape(str(event.get('message') or ''))}"
        "</li>"
        for event in events
    )
    return (
        f"<h2 style=\"margin:24px 0 10px;font-size:18px;\">{html.escape(title)}</h2>"
        f"<ul style=\"margin:8px 0 0 20px;padding:0;\">{rows}</ul>"
    )


def build_html_body(
    report: dict[str, Any],
    counts: dict[str, int],
    *,
    run_url: str,
    event: str,
    sha: str,
    workflow_result: str,
    artifact_result: str,
) -> str:
    failed = counts["workflow_failures"] or counts["artifact_failures"] or counts["failures"]
    status_color = "#991b1b" if failed else "#166534"
    summary_rows = "".join(
        "<tr>"
        f"<td style=\"padding:6px 12px;border-bottom:1px solid #e5e7eb;\">{html.escape(key.replace('_', ' '))}</td>"
        f"<td style=\"padding:6px 12px;border-bottom:1px solid #e5e7eb;text-align:right;\"><strong>{value}</strong></td>"
        "</tr>"
        for key, value in counts.items()
    )
    run_value = (
        f"<a href=\"{html.escape(run_url)}\" style=\"color:#2563eb;\">{html.escape(run_url)}</a>"
        if run_url
        else "unknown"
    )
    body = [
        "<!doctype html><html><body style=\"margin:0;background:#fff;color:#111827;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;font-size:14px;line-height:1.5;\">",
        "<div style=\"max-width:920px;margin:0 auto;padding:24px;\">",
        "<h1 style=\"margin:0 0 8px;font-size:24px;\">Wodby Boilerplate Update Report</h1>",
        "<p style=\"margin:0 0 18px;color:#4b5563;\">Boilerplate update report events were detected.</p>",
        "<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" style=\"border-collapse:collapse;margin-bottom:18px;\">",
        f"<tr><td style=\"padding:2px 14px 2px 0;color:#6b7280;\">Run</td><td>{run_value}</td></tr>",
        f"<tr><td style=\"padding:2px 14px 2px 0;color:#6b7280;\">Event</td><td>{html.escape(event or 'unknown')}</td></tr>",
        f"<tr><td style=\"padding:2px 14px 2px 0;color:#6b7280;\">Commit</td><td>{html.escape(sha or 'unknown')}</td></tr>",
        f"<tr><td style=\"padding:2px 14px 2px 0;color:#6b7280;\">Update job result</td><td style=\"color:{status_color};\"><strong>{html.escape(workflow_result or 'unknown')}</strong></td></tr>",
        f"<tr><td style=\"padding:2px 14px 2px 0;color:#6b7280;\">Artifact download result</td><td style=\"color:{status_color};\"><strong>{html.escape(artifact_result or 'unknown')}</strong></td></tr>",
        f"<tr><td style=\"padding:2px 14px 2px 0;color:#6b7280;\">Report date</td><td>{html.escape(str(report.get('generated_at') or 'unknown'))}</td></tr>",
        "</table>",
        "<h2 style=\"margin:24px 0 10px;font-size:18px;\">Summary</h2>",
        "<table role=\"presentation\" cellspacing=\"0\" cellpadding=\"0\" "
        "style=\"border-collapse:collapse;min-width:360px;border:1px solid #e5e7eb;\">",
        summary_rows,
        "</table>",
    ]
    if counts["workflow_failures"]:
        body.append(
            "<div style=\"margin:20px 0;padding:12px;border:1px solid #fecaca;background:#fef2f2;color:#991b1b;\">"
            "<strong>Workflow Failure</strong><br>One or more update jobs did not complete successfully. Check the run URL above."
            "</div>"
        )
    if counts["artifact_failures"]:
        body.append(
            "<div style=\"margin:20px 0;padding:12px;border:1px solid #fecaca;background:#fef2f2;color:#991b1b;\">"
            "<strong>Report Artifact Failure</strong><br>Update report artifacts could not be downloaded. Check the workflow logs."
            "</div>"
        )
    body.append(html_event_section("Dependency Update Commits", report.get("commits") or []))
    body.append(html_event_section("Validated Dry-run Updates", report.get("validated") or []))
    body.append(html_event_section("Failures", report.get("failures") or []))
    body.append(html_event_section("Other Events", report.get("other_events") or []))
    if report.get("warnings"):
        warning_rows = "".join(f"<li>{html.escape(str(warning))}</li>" for warning in report["warnings"])
        body.append(
            "<h2 style=\"margin:24px 0 10px;font-size:18px;\">Report Warnings</h2>"
            f"<ul style=\"margin:8px 0 0 20px;padding:0;\">{warning_rows}</ul>"
        )
    body.append("</div></body></html>")
    return "".join(body)


def build_subject(counts: dict[str, int], sha: str) -> str:
    failed = counts["workflow_failures"] or counts["artifact_failures"] or counts["failures"]
    status = "failed" if failed else "events"
    short_sha = sha[:7] if sha else "unknown"
    return (
        f"[boilerplates] report {status}: {counts['commits']} commits, "
        f"{counts['validated']} validated, {counts['failures']} failures ({short_sha})"
    )


def split_recipients(value: str) -> list[str]:
    return [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]


def send_email(subject: str, body: str, html_body: str) -> bool:
    smtp_host = os.environ.get("SMTP_HOST", "").strip()
    smtp_port = int(os.environ.get("SMTP_PORT") or "587")
    smtp_user = os.environ.get("SMTP_USERNAME", "").strip()
    smtp_password = os.environ.get("SMTP_PASSWORD", "")
    mail_from = os.environ.get("REPORT_EMAIL_FROM", "").strip() or smtp_user
    recipients = split_recipients(os.environ.get("REPORT_EMAIL_TO", ""))
    use_ssl = os.environ.get("SMTP_SSL", "").lower() in ("1", "true", "yes")
    use_starttls = os.environ.get("SMTP_STARTTLS", "true").lower() not in ("0", "false", "no")

    missing = []
    if not smtp_host:
        missing.append("SMTP_HOST")
    if not mail_from:
        missing.append("REPORT_EMAIL_FROM")
    if not recipients:
        missing.append("REPORT_EMAIL_TO")
    if missing:
        print(f"Email not sent because required configuration is missing: {', '.join(missing)}")
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = mail_from
    message["To"] = ", ".join(recipients)
    message.set_content(body)
    message.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=context, timeout=60) as smtp:
            if smtp_user or smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    else:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=60) as smtp:
            smtp.ehlo()
            if use_starttls:
                smtp.starttls(context=context)
                smtp.ehlo()
            if smtp_user or smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(message)
    return True


def main() -> int:
    args = parse_args()
    report = load_report(Path(args.report_dir))
    counts = event_counts(report, args.workflow_result, args.artifact_result)
    if not has_email_worthy_events(counts):
        print("No boilerplate update events or workflow failures were found.")
        return 0

    subject = build_subject(counts, args.sha)
    body = build_body(
        report,
        counts,
        run_url=args.run_url,
        event=args.event,
        sha=args.sha,
        workflow_result=args.workflow_result,
        artifact_result=args.artifact_result,
    )
    html_body = build_html_body(
        report,
        counts,
        run_url=args.run_url,
        event=args.event,
        sha=args.sha,
        workflow_result=args.workflow_result,
        artifact_result=args.artifact_result,
    )
    print(subject)
    print("")
    print(body)
    if send_email(subject, body, html_body):
        print("Email sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
