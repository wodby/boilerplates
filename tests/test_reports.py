import json
import tempfile
import unittest
from pathlib import Path

from scripts.boilerplate_report_email import (
    build_html_body,
    build_subject,
    event_counts,
    has_email_worthy_events,
)
from scripts.boilerplate_update_report import generate_report, render_markdown


class BoilerplateUpdateReportTest(unittest.TestCase):
    def test_consolidates_and_deduplicates_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            reports = Path(temp_dir)
            first = reports / "first" / "events.jsonl"
            second = reports / "second" / "events.jsonl"
            first.parent.mkdir()
            second.parent.mkdir()
            commit = {"type": "commit", "repo": "wodby/rails-boilerplate", "message": "Update dependencies"}
            failure = {"type": "failure", "repo": "wodby/nextjs-boilerplate", "message": "Dependency update failed"}
            first.write_text("\n".join((json.dumps(commit), json.dumps(failure), "not json")))
            second.write_text(json.dumps(commit) + "\n")

            report = generate_report(reports)

        self.assertEqual(report["totals"]["events"], 2)
        self.assertEqual(report["totals"]["commits"], 1)
        self.assertEqual(report["totals"]["failures"], 1)
        self.assertEqual(report["totals"]["warnings"], 1)
        self.assertEqual(
            report["affected_repos"],
            ["wodby/nextjs-boilerplate", "wodby/rails-boilerplate"],
        )
        markdown = render_markdown(report)
        self.assertIn("Dependency Update Commits", markdown)
        self.assertIn("Report Warnings", markdown)

    def test_empty_report_is_quiet(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = generate_report(Path(temp_dir))

        counts = event_counts(report, "checks=success, update=success", "success")
        self.assertFalse(has_email_worthy_events(counts))


class BoilerplateReportEmailTest(unittest.TestCase):
    def test_workflow_and_update_failures_are_email_worthy(self):
        report = {
            "generated_at": "2026-07-24T00:00:00+00:00",
            "totals": {
                "commits": 1,
                "validated": 0,
                "failures": 1,
                "other_events": 0,
                "warnings": 0,
            },
            "commits": [],
            "validated": [],
            "failures": [],
            "other_events": [],
            "warnings": [],
        }
        counts = event_counts(report, "checks=success, update=failure", "success")

        self.assertTrue(has_email_worthy_events(counts))
        self.assertEqual(
            build_subject(counts, "123456789"),
            "[boilerplates] report failed: 1 commits, 0 validated, 1 failures (1234567)",
        )

    def test_html_body_escapes_event_content(self):
        report = {
            "generated_at": "2026-07-24T00:00:00+00:00",
            "commits": [{"type": "commit", "repo": "wodby/test", "message": "<updated>"}],
            "validated": [],
            "failures": [],
            "other_events": [],
            "warnings": [],
        }
        counts = {
            "workflow_failures": 0,
            "artifact_failures": 0,
            "commits": 1,
            "validated": 0,
            "failures": 0,
            "other_events": 0,
            "report_warnings": 0,
        }

        body = build_html_body(
            report,
            counts,
            run_url="https://example.com/run",
            event="schedule",
            sha="1234567",
            workflow_result="success",
            artifact_result="success",
        )

        self.assertIn("&lt;updated&gt;", body)
        self.assertNotIn("<updated>", body)


if __name__ == "__main__":
    unittest.main()
