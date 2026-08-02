#!/usr/bin/env python3
"""Review and deliberately promote one live skill into this repository."""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path


ALLOWED_SKILLS = frozenset({"skill-scout", "skill-eval-loop"})
ALLOWED_TOP_LEVEL = frozenset({"SKILL.md", "agents", "evals", "references", "scripts", "tests"})
EXCLUDED_NAMES = frozenset({".DS_Store", "__pycache__", ".pytest_cache", ".eval-runs", ".git"})
EXCLUDED_SUFFIXES = (".pyc", ".pyo")


@dataclass(frozen=True)
class FileRecord:
    path: Path
    digest: str
    executable: bool
    textual: bool


@dataclass(frozen=True)
class PromotionPlan:
    modified: tuple[Path, ...]
    added: tuple[Path, ...]
    mode_changed: tuple[Path, ...]
    repository_only: tuple[Path, ...]
    excluded: tuple[Path, ...] = ()


def validate_skill_root(root: Path, label: str) -> None:
    if root.is_symlink():
        raise ValueError(f"{label} skill root must not be a symlink: {root}")
    if not root.is_dir():
        raise ValueError(f"{label} skill root does not exist: {root}")


def inventory(root: Path) -> dict[Path, FileRecord]:
    validate_skill_root(root, "skill")
    records: dict[Path, FileRecord] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError(f"symlinked entry is not allowed: {path}")
        if any(part in EXCLUDED_NAMES for part in relative.parts) or path.name.endswith(EXCLUDED_SUFFIXES):
            continue
        if relative.parts[0] not in ALLOWED_TOP_LEVEL:
            raise ValueError(f"path is outside the allowed skill layout: {relative}")
        if not path.is_file():
            continue
        if len(relative.parts) == 1 and relative.name != "SKILL.md":
            raise ValueError(f"allowed top-level path must be a directory: {relative}")
        data = path.read_bytes()
        records[relative] = FileRecord(
            path=path,
            digest=hashlib.sha256(data).hexdigest(),
            executable=bool(path.stat().st_mode & 0o111),
            textual=b"\0" not in data,
        )
    return records


def classify(repo_files: dict[Path, FileRecord], live_files: dict[Path, FileRecord]) -> PromotionPlan:
    modified: list[Path] = []
    mode_changed: list[Path] = []
    for path in repo_files.keys() & live_files.keys():
        if repo_files[path].digest != live_files[path].digest:
            modified.append(path)
        if repo_files[path].executable != live_files[path].executable:
            mode_changed.append(path)
    return PromotionPlan(
        modified=tuple(sorted(modified)),
        added=tuple(sorted(live_files.keys() - repo_files.keys())),
        mode_changed=tuple(sorted(mode_changed)),
        repository_only=tuple(sorted(repo_files.keys() - live_files.keys())),
    )


def render_plan(plan: PromotionPlan, repo_files: dict[Path, FileRecord], live_files: dict[Path, FileRecord]) -> str:
    lines: list[str] = []
    for path in plan.modified:
        repo = repo_files[path]
        live = live_files[path]
        if repo.textual and live.textual:
            lines.extend(
                unified_diff(
                    repo.path.read_text(errors="replace").splitlines(keepends=True),
                    live.path.read_text(errors="replace").splitlines(keepends=True),
                    fromfile=f"repo/{path}", tofile=f"live/{path}",
                )
            )
        else:
            lines.append(f"binary file changed: {path}\n")
    for path in plan.mode_changed:
        lines.append(f"mode changed: {path}\n")
    for path in plan.added:
        live = live_files[path]
        if live.textual:
            lines.extend(
                unified_diff(
                    [],
                    live.path.read_text(errors="replace").splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile=f"live/{path}",
                )
            )
        else:
            lines.append(f"new binary live file: {path}\n")
    for path in plan.repository_only:
        lines.append(f"repository-only file (not deleted): {path}\n")
    return "".join(lines)


def destination_is_dirty(repo_root: Path, skill: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain", "--", f"skills/{skill}"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise ValueError(f"could not inspect Git status: {result.stderr.strip()}")
    return bool(result.stdout.strip())


def apply_plan(
    plan: PromotionPlan,
    repo_files: dict[Path, FileRecord],
    live_files: dict[Path, FileRecord],
    repo_root: Path,
    skill: str,
    include_new: bool,
) -> None:
    if plan.added and not include_new:
        raise ValueError("new live files require --include-new")
    if destination_is_dirty(repo_root, skill):
        raise ValueError(f"destination scope skills/{skill} is dirty; refusing --apply")
    destination_root = repo_root / "skills" / skill
    paths = (*plan.modified, *plan.mode_changed, *(plan.added if include_new else ()))
    for relative in paths:
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(live_files[relative].path, destination)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--include-new", action="store_true")
    parser.add_argument("--repo-root")
    parser.add_argument("--live-root")
    args = parser.parse_args(argv)
    if args.skill not in ALLOWED_SKILLS:
        parser.error(f"skill {args.skill!r} is not allowed")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).absolute() if args.repo_root else Path(__file__).resolve().parents[1]
    live_root = Path(args.live_root).expanduser().absolute() if args.live_root else Path(
        os.environ.get("AGENTS_SKILLS_ROOT", "~/.agents/skills")
    ).expanduser().absolute()
    try:
        if live_root.is_symlink():
            raise ValueError(f"live root must not be a symlink: {live_root}")
        repo_files = inventory(repo_root / "skills" / args.skill)
        live_files = inventory(live_root / args.skill)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    plan = classify(repo_files, live_files)
    if not (plan.modified or plan.added or plan.mode_changed or plan.repository_only):
        print(f"No drift: {args.skill} is identical.")
        return 0
    print(f"Drift detected for {args.skill}.")
    print(render_plan(plan, repo_files, live_files), end="")
    if args.apply:
        try:
            apply_plan(plan, repo_files, live_files, repo_root, args.skill, args.include_new)
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print("Applied reviewed live changes. Nothing was staged or published.")
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
