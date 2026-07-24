#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


KNOWN_EVENT_TYPES = ("commit", "validated", "failure")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a consolidated Wodby boilerplate update report.")
    parser.add_argument("--events-dir", default="reports", help="Directory containing update event artifacts.")
    parser.add_argument(
        "--output-dir",
        default="boilerplate-update-report",
        help="Directory for the consolidated JSON and Markdown report files.",
    )
    return parser.parse_args()


def load_events(events_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    if not events_dir.exists():
        return events, warnings

    for path in sorted(events_dir.rglob("events.jsonl")):
        for line_number, raw_line in enumerate(path.read_text().splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                warnings.append(f"Could not parse `{path}` line {line_number}: {exc.msg}")
                continue
            if not isinstance(event, dict):
                warnings.append(f"Ignored non-object event in `{path}` line {line_number}.")
                continue

            event_type = str(event.get("type") or "unknown")
            repo = str(event.get("repo") or "unknown")
            message = str(event.get("message") or "")
            key = (event_type, repo, message)
            if key in seen:
                continue
            seen.add(key)
            event["type"] = event_type
            event["repo"] = repo
            event["message"] = message
            events.append(event)

    return (
        sorted(
            events,
            key=lambda event: (
                str(event.get("repo") or ""),
                str(event.get("created_at") or ""),
                str(event.get("type") or ""),
            ),
        ),
        warnings,
    )


def generate_report(events_dir: Path) -> dict[str, Any]:
    events, warnings = load_events(events_dir)
    grouped = {
        event_type: [event for event in events if event.get("type") == event_type]
        for event_type in KNOWN_EVENT_TYPES
    }
    other_events = [event for event in events if event.get("type") not in KNOWN_EVENT_TYPES]
    affected_repos = sorted({str(event["repo"]) for event in events if event.get("repo")})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "totals": {
            "events": len(events),
            "affected_repos": len(affected_repos),
            "commits": len(grouped["commit"]),
            "validated": len(grouped["validated"]),
            "failures": len(grouped["failure"]),
            "other_events": len(other_events),
            "warnings": len(warnings),
        },
        "affected_repos": affected_repos,
        "events": events,
        "commits": grouped["commit"],
        "validated": grouped["validated"],
        "failures": grouped["failure"],
        "other_events": other_events,
        "warnings": warnings,
    }


def append_events(lines: list[str], title: str, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    lines.extend((f"## {title}", ""))
    for event in events:
        event_type = str(event.get("type") or "event").replace("_", " ")
        lines.append(f"- `{event.get('repo') or 'unknown'}`: {event_type}: {event.get('message') or ''}")
    lines.append("")


def render_markdown(report: dict[str, Any]) -> str:
    totals = report["totals"]
    lines = [
        "# Wodby Boilerplate Update Report",
        "",
        f"Report date: {report['generated_at']}",
        "",
        "## Summary",
        "",
        f"- Events: {totals['events']}",
        f"- Affected repositories: {totals['affected_repos']}",
        f"- Dependency update commits: {totals['commits']}",
        f"- Validated dry-run updates: {totals['validated']}",
        f"- Failures: {totals['failures']}",
        f"- Other events: {totals['other_events']}",
        f"- Report warnings: {totals['warnings']}",
        "",
    ]

    append_events(lines, "Dependency Update Commits", report["commits"])
    append_events(lines, "Validated Dry-run Updates", report["validated"])
    append_events(lines, "Failures", report["failures"])
    append_events(lines, "Other Events", report["other_events"])

    if report["warnings"]:
        lines.extend(("## Report Warnings", ""))
        lines.extend(f"- {warning}" for warning in report["warnings"])
        lines.append("")

    if not report["events"] and not report["warnings"]:
        lines.extend(("No reportable boilerplate update events were found.", ""))

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = generate_report(Path(args.events_dir))
    markdown = render_markdown(report)
    (output_dir / "boilerplate-update-report.json").write_text(json.dumps(report, indent=2) + "\n")
    (output_dir / "boilerplate-update-report.md").write_text(markdown)
    print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
