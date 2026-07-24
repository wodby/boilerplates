#!/usr/bin/env python3

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "boilerplates.yml"
UPDATE_FIELDS = (
    "ecosystem",
    "profile",
    "update_image",
    "validation_images",
    "allowed_changes",
)


def load_generic_updates(catalog_path: Path) -> list[dict[str, Any]]:
    catalog = yaml.safe_load(catalog_path.read_text()) or {}
    entries: list[dict[str, Any]] = []

    for boilerplate in catalog.get("boilerplates") or []:
        updates = boilerplate.get("dependency_updates") or {}
        if updates.get("mode") != "generic":
            continue

        entry = {
            "name": boilerplate["name"],
            "repo": boilerplate["repository"],
        }
        entry.update({field: updates[field] for field in UPDATE_FIELDS})
        entries.append(entry)

    return entries


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read generic dependency-update settings from the boilerplate catalog."
    )
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("matrix")
    entry_parser = subparsers.add_parser("entry")
    entry_parser.add_argument("name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    entries = load_generic_updates(args.catalog)

    if args.command == "matrix":
        print(json.dumps([entry["name"] for entry in entries], separators=(",", ":")))
        return 0

    entry = next((item for item in entries if item["name"] == args.name), None)
    if entry is None:
        raise SystemExit(f"Unknown generic boilerplate: {args.name}")
    print(json.dumps(entry, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
