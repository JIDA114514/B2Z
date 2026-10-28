#!/usr/bin/env python3
"""Index experiments or migrate legacy receiver results without changing evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from experiment_tools.reporting import (EXPERIMENTS, PROJECT, rebuild_index, receiver_role,
                                        resolve_recorded_path, write_json)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def legacy_plan(project=PROJECT):
    """Only attach replays when config.iq_file identifies their source capture."""
    target = project / "python/experiments"
    plan, groups, captures = {}, {}, {}
    pending = []
    for family, role in (("exadv_rx", "ble"), ("zigbee_rx", "zigbee")):
        directory = project / "python" / family / "results"
        for path in sorted(directory.glob("*.summary.json")):
            value = json.loads(path.read_text())
            if not isinstance(value, dict) or not receiver_role(value):
                continue
            prefix = path.name.removesuffix(".summary.json")
            iq = value.get("config", {}).get("iq_file")
            if iq:
                pending.append((directory, prefix, role, iq))
                continue
            session = target / ("history_" + role + "_" + prefix)
            groups[str(session)] = {"origin": "legacy_capture", "legacy_source": str(directory.relative_to(project) / prefix)}
            destination = session / "captures" / role / prefix
            captures[(directory.relative_to(project) / prefix).as_posix()] = session
            assign_prefix(plan, directory, prefix, destination, project)
    for directory, prefix, role, iq in pending:
        source = str(iq)
        if "python/" in source:
            source = "python/" + source.split("python/", 1)[1]
        source = str(Path(source).with_suffix(""))
        session = captures.get(source, target / ("history_" + role + "_" + prefix))
        groups.setdefault(str(session), {"origin": "legacy_replay", "legacy_source": source})
        assign_prefix(plan, directory, prefix, session / "analyses" / (directory.parent.name + "_" + prefix) / role / prefix, project)
    for family in ("exadv_rx", "zigbee_rx", "sync_validation"):
        directory = project / "python" / family / "results"
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.name in (".gitignore", "README.md", "archive.manifest.example.json"):
                continue
            original = path.relative_to(project).as_posix()
            if original in plan:
                continue
            relative = path.relative_to(directory)
            if family == "sync_validation" and len(relative.parts) > 1:
                session = target / ("history_sync_" + relative.parts[0])
                destination = session / "analyses" / "legacy" / Path(*relative.parts[1:])
                groups[str(session)] = {"origin": "legacy_group", "legacy_source": str((directory / relative.parts[0]).relative_to(project)),
                                        "scope": "Original grouping preserved; live/replay remain distinguished by each receiver config."}
            else:
                session = target / ("history_" + family + "_reviews")
                destination = session / "analyses" / "legacy" / relative
                groups[str(session)] = {"origin": "legacy_cross_run_analysis", "legacy_source": str(directory.relative_to(project))}
            plan[original] = {"destination": destination.relative_to(project).as_posix()}
    return plan, groups


def assign_prefix(plan, directory, prefix, destination, project):
    for path in directory.glob(prefix + ".*"):
        plan[path.relative_to(project).as_posix()] = {
            "destination": str(destination.relative_to(project)) + path.name[len(prefix):]}


def migrate(apply=False):
    manifest_path = EXPERIMENTS / "migration.manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["status"] == "complete":
            print(f"Already migrated: {len(manifest['paths'])} files. Rebuilding reports/index.")
            if apply:
                rebuild_index()
            return
        plan, groups = manifest["paths"], manifest["groups"]
    else:
        plan, absolute_groups = legacy_plan()
        groups = {str(Path(path).relative_to(PROJECT)): value for path, value in absolute_groups.items()}
        manifest = {"schema": "experiment_migration_v1", "status": "planned", "paths": plan, "groups": groups,
                    "policy": "Original artifact bytes preserved. Paths in historical evidence are resolved via this manifest. No grouping by Run ID alone."}
    print(f"Migration: {len(plan)} files -> {len(groups)} experiment directories.", flush=True)
    if not apply:
        print("Preview only; use --apply to move artifacts and generate reports/index.")
        return
    for source, entry in plan.items():
        old, new = PROJECT / source, PROJECT / entry["destination"]
        if old.exists() and new.exists():
            raise FileExistsError(f"both source and destination exist: {source}")
        current = old if old.exists() else new
        if not current.is_file():
            raise FileNotFoundError(source)
        if "sha256" not in entry:
            entry.update(bytes=current.stat().st_size, sha256=sha256(current))
        elif current.stat().st_size != entry["bytes"] or sha256(current) != entry["sha256"]:
            raise ValueError(f"artifact changed since migration plan: {source}")
    # Persist the complete path map BEFORE renaming; an interrupted move is resumable.
    write_json(manifest_path, manifest)
    for source, entry in plan.items():
        old, new = PROJECT / source, PROJECT / entry["destination"]
        new.parent.mkdir(parents=True, exist_ok=True)
        if old.exists():
            old.rename(new)
    for name, metadata in groups.items():
        directory = PROJECT / name
        config = directory / "experiment.config.json"
        if not config.exists():
            write_json(config, {"schema": "experiment_v1", "experiment_id": directory.name, **metadata})
    manifest["status"] = "complete"
    write_json(manifest_path, manifest)
    print("Moved original files without editing their contents.", flush=True)
    print("Indexed:", rebuild_index(), flush=True)


def verify():
    manifest = json.loads((EXPERIMENTS / "migration.manifest.json").read_text())
    failures = []
    for source, entry in manifest["paths"].items():
        path = PROJECT / entry["destination"]
        if not path.is_file() or path.stat().st_size != entry["bytes"] or sha256(path) != entry["sha256"]:
            failures.append(source)
    if failures:
        raise ValueError("Migration verification failed: " + ", ".join(failures))
    print(f"Verified byte sizes and SHA-256 for {len(manifest['paths'])} migrated artifacts.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("index", "migrate", "verify", "locate"))
    parser.add_argument("path", nargs="?", help="original project-relative or absolute artifact path for locate")
    parser.add_argument("--apply", action="store_true", help="execute migration; otherwise preview")
    args = parser.parse_args()
    if args.command == "migrate":
        migrate(args.apply)
    elif args.command == "verify":
        verify()
    elif args.command == "locate":
        if not args.path:
            parser.error("locate requires an artifact path")
        print(resolve_recorded_path(args.path))
    else:
        print("Indexed experiments / receiver records:", rebuild_index())


if __name__ == "__main__":
    main()
