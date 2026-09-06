import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from scripts.update_config import load_generic_updates, load_specialized_updates
from scripts.validate import CatalogError, actual_consumers, catalog_consumers


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "boilerplates.yml"
UPDATER_PATH = ROOT / "scripts" / "update-dependencies.sh"
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "update.yml"

EXPECTED_BOILERPLATES = {
    "angular",
    "django",
    "expressjs",
    "fastapi",
    "flask",
    "go",
    "laravel",
    "nextjs",
    "php-package",
    "python",
    "rails",
    "react",
    "ruby",
    "slack-inviter",
    "vue",
}

EXPECTED_SPECIALIZED_BOILERPLATES = {
    "drupal-cms",
    "drupal-vanilla",
    "wordpress-vanilla",
}

EXPECTED_DEPENDENCY_FILES = {
    "bundler": ["Gemfile.lock"],
    "composer": ["composer.lock"],
    "go": ["go.mod", "go.sum"],
    "npm": ["package-lock.json"],
    "uv": ["uv.lock"],
}

EXPECTED_PROFILES = {
    "django",
    "expressjs",
    "go",
    "node-check",
    "npm-build",
    "phpunit",
    "pytest",
    "python",
    "rails",
    "ruby",
}


class BoilerplateUpdateConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = yaml.safe_load(CATALOG_PATH.read_text())
        cls.entries = load_generic_updates(CATALOG_PATH)
        cls.specialized_entries = load_specialized_updates(CATALOG_PATH)

    def test_inventory_is_complete_and_unique(self):
        names = [entry["name"] for entry in self.entries]

        self.assertEqual(len(names), len(set(names)))
        self.assertEqual(set(names), EXPECTED_BOILERPLATES)

    def test_entries_use_supported_profiles_and_dependency_files(self):
        for entry in self.entries:
            with self.subTest(boilerplate=entry["name"]):
                expected_repository = {
                    "slack-inviter": "wodby/slack-inviter",
                }.get(entry["name"], f"wodby/{entry['name']}-boilerplate")
                self.assertEqual(entry["repo"], expected_repository)
                self.assertIn(entry["ecosystem"], EXPECTED_DEPENDENCY_FILES)
                self.assertIn(entry["profile"], EXPECTED_PROFILES)
                self.assertEqual(
                    entry["allowed_changes"],
                    EXPECTED_DEPENDENCY_FILES[entry["ecosystem"]],
                )
                self.assertTrue(entry["update_image"].startswith("wodby/"))
                self.assertGreaterEqual(len(entry["validation_images"]), 2)

    def test_update_ownership_matches_mode(self):
        for entry in self.catalog["boilerplates"]:
            updates = entry.get("dependency_updates")
            if not updates:
                continue
            with self.subTest(boilerplate=entry["name"]):
                self.assertEqual(updates["repository"], "wodby/boilerplates")

    def test_service_consumers_use_canonical_boilerplate_key(self):
        _, consumers = catalog_consumers(self.catalog)

        self.assertEqual(len(consumers), 24)
        for entry in self.catalog["boilerplates"]:
            for service in entry["services"]:
                self.assertIn("boilerplate", service)
                self.assertNotIn("template", service)

    def test_workflow_matrix_comes_from_catalog(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "update_config.py"), "matrix"],
            capture_output=True,
            text=True,
            check=True,
        )
        workflow = WORKFLOW_PATH.read_text()

        self.assertEqual(set(json.loads(result.stdout)), EXPECTED_BOILERPLATES)
        self.assertIn(
            "fromJSON(needs.checks.outputs.boilerplates)",
            workflow,
        )

    def test_specialized_workflow_matrix_comes_from_catalog(self):
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "update_config.py"), "specialized-matrix"],
            capture_output=True,
            text=True,
            check=True,
        )
        workflow = WORKFLOW_PATH.read_text()

        self.assertEqual(
            {entry["name"] for entry in self.specialized_entries},
            EXPECTED_SPECIALIZED_BOILERPLATES,
        )
        self.assertEqual(set(json.loads(result.stdout)), EXPECTED_SPECIALIZED_BOILERPLATES)
        self.assertIn(
            "fromJSON(needs.checks.outputs.specialized)",
            workflow,
        )


class AllowedChangesTest(unittest.TestCase):
    def run_check(self, repo: Path, allowed: list[str]) -> subprocess.CompletedProcess:
        allowed_json = json.dumps(allowed)
        script = (
            f'. "{UPDATER_PATH}"; '
            f'_assert_only_allowed_boilerplate_changes "{repo}" \'{allowed_json}\''
        )
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )

    def make_repo(self) -> Path:
        temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp_dir)
        subprocess.run(["git", "init", "-q", str(temp_dir)], check=True)
        subprocess.run(
            ["git", "-C", str(temp_dir), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(temp_dir), "config", "user.name", "Test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(temp_dir), "config", "commit.gpgsign", "false"],
            check=True,
        )
        (temp_dir / "uv.lock").write_text("old\n")
        (temp_dir / "pyproject.toml").write_text("[project]\n")
        subprocess.run(["git", "-C", str(temp_dir), "add", "."], check=True)
        subprocess.run(["git", "-C", str(temp_dir), "commit", "-qm", "Initial"], check=True)
        return temp_dir

    def test_allows_configured_dependency_file(self):
        repo = self.make_repo()
        (repo / "uv.lock").write_text("new\n")

        result = self.run_check(repo, ["uv.lock"])

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rejects_manifest_change(self):
        repo = self.make_repo()
        (repo / "pyproject.toml").write_text("[project]\nname = 'changed'\n")

        result = self.run_check(repo, ["uv.lock"])

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected file", result.stderr)


class ValidationEnvironmentTest(unittest.TestCase):
    def run_validation(self, command: str) -> subprocess.CompletedProcess:
        script = f'''
. "{UPDATER_PATH}"
_boilerplate_run() {{
    printf '%s\\n' "$*"
}}
_boilerplate_build() {{
    printf 'build %s\n' "$*"
}}
{command}
'''
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_django_validation_supplies_secret_without_enabling_debug(self):
        result = self.run_validation(
            "_validate_uv_boilerplate django django /tmp/repo /tmp/repo "
            "'[\"wodby/python:test\"]'"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "env DJANGO_SECRET_KEY=boilerplate-validation-only "
            "uv run python manage.py check",
            result.stdout,
        )
        self.assertIn(
            "env DJANGO_SECRET_KEY=boilerplate-validation-only "
            "uv run python manage.py test",
            result.stdout,
        )
        self.assertNotIn("DJANGO_DEBUG", result.stdout)

    def test_laravel_validation_supplies_application_key(self):
        result = self.run_validation(
            "_validate_composer_boilerplate laravel /tmp/repo "
            "'[\"wodby/php:test\"]'"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "env APP_KEY=boilerplatevalidationkey00000000 "
            "vendor/bin/phpunit --do-not-cache-result",
            result.stdout,
        )

    def test_plain_phpunit_validation_does_not_receive_laravel_key(self):
        result = self.run_validation(
            "_validate_composer_boilerplate php-package /tmp/repo "
            "'[\"wodby/php:test\"]'"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("APP_KEY", result.stdout)
        self.assertIn(
            "vendor/bin/phpunit --do-not-cache-result",
            result.stdout,
        )

    def test_node_check_validation_runs_checks_for_each_image(self):
        result = self.run_validation(
            "_validate_npm_boilerplate slack-inviter node-check /tmp/repo "
            "/tmp/repo '[\"wodby/node:22\",\"wodby/node:26\"]'"
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.count("npm run check"), 2)
        self.assertEqual(result.stdout.count("build slack-inviter node-check"), 2)


class ServiceManifestConsumerTest(unittest.TestCase):
    class FakeClient:
        def __init__(self, build: dict):
            self.build = build

        def get_file(self, repository: str, path: str) -> str | None:
            if repository == "wodby/service-demo" and path == "service.yml":
                return yaml.safe_dump({"name": "demo", "build": self.build})
            return None

    def test_reads_canonical_boilerplates(self):
        consumers = actual_consumers(
            self.FakeClient(
                {
                    "boilerplates": [
                        {
                            "name": "demo",
                            "repo": "https://github.com/wodby/demo-boilerplate",
                            "branch": "main",
                        }
                    ]
                }
            ),
            ["wodby/service-demo"],
        )

        self.assertIn(("wodby/service-demo", "service.yml", "demo"), consumers)

    def test_reads_legacy_templates_during_rollout(self):
        consumers = actual_consumers(
            self.FakeClient(
                {
                    "templates": [
                        {
                            "name": "demo",
                            "repo": "https://github.com/wodby/demo-boilerplate",
                            "branch": "main",
                        }
                    ]
                }
            ),
            ["wodby/service-demo"],
        )

        self.assertIn(("wodby/service-demo", "service.yml", "demo"), consumers)

    def test_rejects_canonical_and_legacy_fields_together(self):
        with self.assertRaisesRegex(CatalogError, "defines both"):
            actual_consumers(
                self.FakeClient({"boilerplates": [], "templates": []}),
                ["wodby/service-demo"],
            )


if __name__ == "__main__":
    unittest.main()
