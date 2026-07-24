#!/usr/bin/env python3

import argparse
import base64
import os
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
import yaml


GITHUB_REPO_URL_RE = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)
SERVICE_REPO_RE = re.compile(
    r"https://github\.com/wodby/(?P<repo>service-[A-Za-z0-9._-]+)(?:/)?(?=[)\s|]|$)",
    re.IGNORECASE,
)
MANAGED_SERVICES_HEADING = "## Managed services"
GENERIC_UPDATE_REPOSITORY = "wodby/boilerplates"
SPECIALIZED_UPDATE_REPOSITORY = "wodby/boilerplates"
DEPENDENCY_FILES = {
    "bundler": ["Gemfile.lock"],
    "composer": ["composer.lock"],
    "go": ["go.mod", "go.sum"],
    "npm": ["package-lock.json"],
    "uv": ["uv.lock"],
}
UPDATE_PROFILES = {
    "django",
    "expressjs",
    "go",
    "npm-build",
    "phpunit",
    "pytest",
    "python",
    "rails",
    "ruby",
}


class CatalogError(RuntimeError):
    pass


class GitHubClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"
        self.cache: dict[tuple[str, str], str | None] = {}

    def get_file(self, repository: str, path: str) -> str | None:
        key = (repository, path)
        if key in self.cache:
            return self.cache[key]

        url = f"https://api.github.com/repos/{repository}/contents/{quote(path)}"
        response = self.session.get(url, timeout=60)
        if response.status_code == 404:
            self.cache[key] = None
            return None
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("encoding") != "base64":
            raise CatalogError(f"GitHub returned unsupported content for {repository}:{path}")
        content = base64.b64decode(str(payload.get("content") or "")).decode("utf-8")
        self.cache[key] = content
        return content


def parse_repository(value: Any) -> str:
    text = str(value or "").strip().removesuffix(".git").strip("/")
    match = GITHUB_REPO_URL_RE.match(str(value or "").strip())
    if match:
        return f"{match.group('owner')}/{match.group('repo')}"
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", text):
        return text
    raise CatalogError(f"invalid GitHub repository: {value!r}")


def load_yaml(text: str, label: str) -> dict[str, Any]:
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise CatalogError(f"{label} did not decode to a mapping")
    return data


def managed_service_repositories(client: GitHubClient, services_repository: str) -> list[str]:
    readme = client.get_file(services_repository, "README.md")
    if readme is None:
        raise CatalogError(f"{services_repository} has no README.md")
    _, separator, managed = readme.partition(MANAGED_SERVICES_HEADING)
    if not separator:
        raise CatalogError(f"{services_repository} README has no {MANAGED_SERVICES_HEADING!r} section")
    return sorted({f"wodby/{repo}" for repo in SERVICE_REPO_RE.findall(managed)})


def manifest_paths(client: GitHubClient, repository: str) -> list[str]:
    if client.get_file(repository, "service.yml") is not None:
        return ["service.yml"]
    index_text = client.get_file(repository, "index.yml")
    if index_text is None:
        raise CatalogError(f"{repository} has neither service.yml nor index.yml")
    index = load_yaml(index_text, f"{repository}:index.yml")
    paths = [f"{str(item).strip().strip('/')}/service.yml" for item in index.get("services") or []]
    return [path for path in paths if not path.startswith("/service.yml")]


def actual_consumers(client: GitHubClient, repositories: list[str]) -> dict[tuple[str, str, str], dict[str, Any]]:
    consumers: dict[tuple[str, str, str], dict[str, Any]] = {}
    for repository in repositories:
        for manifest in manifest_paths(client, repository):
            manifest_text = client.get_file(repository, manifest)
            if manifest_text is None:
                raise CatalogError(f"{repository}:{manifest} was not found")
            service = load_yaml(manifest_text, f"{repository}:{manifest}")
            build = service.get("build") if isinstance(service.get("build"), dict) else {}
            boilerplates = build.get("boilerplates")
            legacy_templates = build.get("templates")
            if boilerplates is not None and legacy_templates is not None:
                raise CatalogError(
                    f"{repository}:{manifest} defines both build.boilerplates "
                    "and legacy build.templates"
                )
            field = "boilerplates" if boilerplates is not None else "templates"
            boilerplates = boilerplates if boilerplates is not None else legacy_templates
            boilerplates = boilerplates or []
            if not isinstance(boilerplates, list):
                raise CatalogError(f"{repository}:{manifest} build.{field} is not a list")
            for boilerplate in boilerplates:
                if not isinstance(boilerplate, dict):
                    raise CatalogError(f"{repository}:{manifest} contains a non-mapping build boilerplate")
                name = str(boilerplate.get("name") or "").strip()
                if not name:
                    raise CatalogError(f"{repository}:{manifest} contains a build boilerplate without a name")
                key = (repository, manifest, name)
                if key in consumers:
                    raise CatalogError(f"duplicate service boilerplate reference: {key}")
                consumers[key] = {
                    "repository": parse_repository(boilerplate.get("repo")),
                    "branch": str(boilerplate.get("branch") or "") or None,
                    "tag": str(boilerplate.get("tag") or "") or None,
                    "pipeline": str(boilerplate.get("pipeline") or "") or None,
                }
    return consumers


def catalog_consumers(catalog: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    if catalog.get("version") != 1:
        raise CatalogError("boilerplates.yml version must be 1")
    boilerplates = catalog.get("boilerplates") or []
    if not isinstance(boilerplates, list):
        raise CatalogError("boilerplates must be a list")

    names: set[str] = set()
    consumers: dict[tuple[str, str, str], dict[str, Any]] = {}
    for boilerplate in boilerplates:
        if not isinstance(boilerplate, dict):
            raise CatalogError("boilerplate entries must be mappings")
        name = str(boilerplate.get("name") or "").strip()
        if not name or name in names:
            raise CatalogError(f"boilerplate name is missing or duplicated: {name!r}")
        names.add(name)

        repository = parse_repository(boilerplate.get("repository"))
        accepted_repositories = {repository}
        accepted_repositories.update(parse_repository(alias) for alias in boilerplate.get("aliases") or [])
        if boilerplate.get("managed"):
            updates = boilerplate.get("dependency_updates")
            if not isinstance(updates, dict) or not updates.get("repository") or not updates.get("mode"):
                raise CatalogError(f"managed boilerplate {name!r} has no dependency_updates mapping")
            mode = str(updates["mode"])
            update_repository = parse_repository(updates["repository"])
            if mode == "generic":
                if update_repository != GENERIC_UPDATE_REPOSITORY:
                    raise CatalogError(
                        f"generic boilerplate {name!r} updates must be owned by "
                        f"{GENERIC_UPDATE_REPOSITORY}"
                    )
                missing = [
                    field
                    for field in (
                        "ecosystem",
                        "profile",
                        "update_image",
                        "validation_images",
                        "allowed_changes",
                    )
                    if not updates.get(field)
                ]
                if missing:
                    raise CatalogError(
                        f"generic boilerplate {name!r} is missing update fields: {missing}"
                    )
                ecosystem = str(updates["ecosystem"])
                if ecosystem not in DEPENDENCY_FILES:
                    raise CatalogError(
                        f"generic boilerplate {name!r} has unsupported ecosystem {ecosystem!r}"
                    )
                if updates["allowed_changes"] != DEPENDENCY_FILES[ecosystem]:
                    raise CatalogError(
                        f"generic boilerplate {name!r} has invalid allowed_changes"
                    )
                if updates["profile"] not in UPDATE_PROFILES:
                    raise CatalogError(
                        f"generic boilerplate {name!r} has unsupported profile "
                        f"{updates['profile']!r}"
                    )
                validation_images = updates["validation_images"]
                if not isinstance(validation_images, list) or len(validation_images) < 2:
                    raise CatalogError(
                        f"generic boilerplate {name!r} must validate against at least two images"
                    )
            elif mode == "specialized":
                if update_repository != SPECIALIZED_UPDATE_REPOSITORY:
                    raise CatalogError(
                        f"specialized boilerplate {name!r} updates must be owned by "
                        f"{SPECIALIZED_UPDATE_REPOSITORY}"
                    )
            else:
                raise CatalogError(
                    f"managed boilerplate {name!r} has unsupported update mode {mode!r}"
                )

        services = boilerplate.get("services") or []
        if not isinstance(services, list) or not services:
            raise CatalogError(f"boilerplate {name!r} has no service consumers")
        for service in services:
            if not isinstance(service, dict):
                raise CatalogError(f"boilerplate {name!r} has a non-mapping service consumer")
            service_repository = parse_repository(service.get("repository"))
            manifest = str(service.get("manifest") or "").strip()
            boilerplate_name = str(service.get("boilerplate") or "").strip()
            if not manifest or not boilerplate_name:
                raise CatalogError(f"boilerplate {name!r} has an incomplete service consumer")
            ref = service.get("ref") if isinstance(service.get("ref"), dict) else {}
            branch = str(ref.get("branch") or "") or None
            tag = str(ref.get("tag") or "") or None
            if bool(branch) == bool(tag):
                raise CatalogError(
                    f"{service_repository}:{manifest}:{boilerplate_name} "
                    "must define exactly one branch or tag"
                )
            key = (service_repository, manifest, boilerplate_name)
            if key in consumers:
                raise CatalogError(f"duplicate catalog service boilerplate reference: {key}")
            consumers[key] = {
                "repositories": accepted_repositories,
                "branch": branch,
                "tag": tag,
                "pipeline": str(service.get("pipeline") or "") or None,
                "boilerplate": name,
            }
    return boilerplates, consumers


def validate(catalog_path: Path, services_repository: str) -> list[str]:
    catalog = load_yaml(catalog_path.read_text(), str(catalog_path))
    boilerplates, expected = catalog_consumers(catalog)
    client = GitHubClient()
    service_repositories = managed_service_repositories(client, services_repository)
    actual = actual_consumers(client, service_repositories)

    errors: list[str] = []
    for key in sorted(actual.keys() - expected.keys()):
        errors.append(f"service boilerplate is missing from catalog: {':'.join(key)}")
    for key in sorted(expected.keys() - actual.keys()):
        errors.append(f"catalog consumer is not present in service manifests: {':'.join(key)}")
    for key in sorted(actual.keys() & expected.keys()):
        actual_item = actual[key]
        expected_item = expected[key]
        if actual_item["repository"] not in expected_item["repositories"]:
            errors.append(
                f"{':'.join(key)} repository is {actual_item['repository']}, "
                f"expected one of {sorted(expected_item['repositories'])}"
            )
        for field in ("branch", "tag", "pipeline"):
            if actual_item[field] != expected_item[field]:
                errors.append(
                    f"{':'.join(key)} {field} is {actual_item[field]!r}, "
                    f"expected {expected_item[field]!r}"
                )

    if not errors:
        print(
            f"Validated {len(boilerplates)} boilerplates and {len(actual)} consumers "
            f"across {len(service_repositories)} service repositories."
        )
    return errors


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate the Wodby boilerplate catalog against service manifests.")
    parser.add_argument("--catalog", type=Path, default=Path("boilerplates.yml"))
    parser.add_argument("--services-repository", default="wodby/services")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        errors = validate(args.catalog, args.services_repository)
    except Exception as exc:
        print(f"Catalog validation failed: {exc}", file=sys.stderr)
        return 1
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
