#!/usr/bin/env python3
"""Review and deliberately promote one live skill into this repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from difflib import unified_diff
from pathlib import Path


ALLOWED_SKILLS = frozenset({"skill-scout", "triangulate-me"})
ALLOWED_TOP_LEVEL = frozenset({"SKILL.md", "agents", "evals", "references", "scripts", "tests"})
EXCLUDED_NAMES = frozenset({".DS_Store", "__pycache__", ".pytest_cache", ".eval-runs", ".git"})
EXCLUDED_SUFFIXES = (".pyc", ".pyo")
TRANSACTION_SCHEMA = "tink-skill-promotion-transaction-v1"


class PromotionRecoveryError(ValueError):
    """A failed swap needs manual recovery from a retained backup."""


@dataclass(frozen=True)
class FileRecord:
    path: Path
    digest: str
    mode: int
    textual: bool
    data: bytes


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


def _read_file_record(path: Path) -> FileRecord:
    try:
        with path.open("rb") as stream:
            data = stream.read()
            mode = stat.S_IMODE(os.fstat(stream.fileno()).st_mode)
    except OSError as error:
        raise ValueError(f"could not inventory {path}: {error}") from error
    return FileRecord(
        path=path,
        digest=hashlib.sha256(data).hexdigest(),
        mode=mode,
        textual=b"\0" not in data,
        data=data,
    )


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
        records[relative] = _read_file_record(path)
    return records


def physical_inventory(root: Path) -> dict[Path, FileRecord]:
    """Inventory every regular destination file, including ignored artifacts."""
    validate_skill_root(root, "skill")
    records: dict[Path, FileRecord] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if path.is_symlink():
            raise ValueError(f"symlinked entry is not allowed: {path}")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError(f"special filesystem entry is not allowed: {path}")
        records[relative] = _read_file_record(path)
    return records


def classify(repo_files: dict[Path, FileRecord], live_files: dict[Path, FileRecord]) -> PromotionPlan:
    modified: list[Path] = []
    mode_changed: list[Path] = []
    for path in repo_files.keys() & live_files.keys():
        if repo_files[path].digest != live_files[path].digest:
            modified.append(path)
        if repo_files[path].mode != live_files[path].mode:
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
                    repo.data.decode(errors="replace").splitlines(keepends=True),
                    live.data.decode(errors="replace").splitlines(keepends=True),
                    fromfile=f"repo/{path}", tofile=f"live/{path}",
                )
            )
        else:
            lines.append(f"binary file changed: {path}\n")
    for path in plan.mode_changed:
        lines.append(
            f"mode changed: {path} "
            f"({repo_files[path].mode:04o} -> {live_files[path].mode:04o})\n"
        )
    for path in plan.added:
        live = live_files[path]
        lines.append(f"new file mode: {path} ({live.mode:04o})\n")
        if live.textual:
            lines.extend(
                unified_diff(
                    [],
                    live.data.decode(errors="replace").splitlines(keepends=True),
                    fromfile="/dev/null",
                    tofile=f"live/{path}",
                )
            )
        else:
            lines.append(f"new binary live file: {path}\n")
    for path in plan.repository_only:
        lines.append(f"repository-only file (not deleted): {path}\n")
    return "".join(lines)


def _inventory_manifest(records: dict[Path, FileRecord]) -> list[dict[str, str]]:
    return [
        {
            "path": path.as_posix(),
            "sha256": records[path].digest,
            "mode": f"{records[path].mode:04o}",
        }
        for path in sorted(records)
    ]


def review_snapshot(
    *,
    skill: str,
    repo_files: dict[Path, FileRecord],
    live_files: dict[Path, FileRecord],
    include_new: bool,
) -> str:
    payload = {
        "schema": "tink-skill-promotion-review-v1",
        "skill": skill,
        "include_new": include_new,
        "repository": _inventory_manifest(repo_files),
        "live": _inventory_manifest(live_files),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _same_inventory(
    left: dict[Path, FileRecord],
    right: dict[Path, FileRecord],
) -> bool:
    return _inventory_manifest(left) == _inventory_manifest(right)


def _validate_skills_root(repo_root: Path) -> Path:
    if repo_root.is_symlink():
        raise ValueError(f"repository root must not be a symlink: {repo_root}")
    skills_root = repo_root / "skills"
    if skills_root.is_symlink():
        raise ValueError(f"repository skills root must not be a symlink: {skills_root}")
    if not skills_root.is_dir():
        raise ValueError(f"repository skills root does not exist: {skills_root}")
    return skills_root


def _validate_destination_chain(repo_root: Path, skill: str) -> Path:
    skills_root = _validate_skills_root(repo_root)
    destination_root = skills_root / skill
    validate_skill_root(destination_root, "repository")
    return destination_root


def _write_transaction_marker(transaction_root: Path, skill: str) -> None:
    marker = {
        "schema": TRANSACTION_SCHEMA,
        "skill": skill,
    }
    transaction_root.joinpath("transaction.json").write_text(
        json.dumps(marker, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _validated_transaction_roots(skills_root: Path, skill: str) -> list[Path]:
    roots: list[Path] = []
    for root in sorted(skills_root.glob(f".{skill}.promote-*")):
        if root.is_symlink() or not root.is_dir():
            raise ValueError(
                f"invalid promotion transaction path; inspect manually: {root}"
            )
        marker_path = root / "transaction.json"
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(
                f"invalid promotion transaction marker; inspect manually: {root}"
            ) from error
        if marker != {"schema": TRANSACTION_SCHEMA, "skill": skill}:
            raise ValueError(
                f"unexpected promotion transaction marker; inspect manually: {root}"
            )
        roots.append(root)
    return roots


def recover_interrupted_promotion(repo_root: Path, skill: str) -> tuple[Path, ...]:
    """Restore an unambiguous old tree left in the two-rename commit gap."""
    skills_root = _validate_skills_root(repo_root)
    transactions = _validated_transaction_roots(skills_root, skill)
    if not transactions:
        return ()
    destination = skills_root / skill
    rendered = ", ".join(str(path) for path in transactions)
    if destination.exists() or destination.is_symlink():
        if all(
            {path.name for path in transaction.iterdir()} == {"transaction.json"}
            for transaction in transactions
        ):
            for transaction in transactions:
                try:
                    shutil.rmtree(transaction)
                except OSError as error:
                    raise ValueError(
                        "could not remove completed promotion transaction "
                        f"{transaction}: {error}"
                    ) from error
            return tuple(transactions)
        raise ValueError(
            "unfinished promotion transaction retained while the destination "
            f"still exists; no state was removed. Inspect: {rendered}"
        )
    if len(transactions) != 1:
        raise ValueError(
            "destination is missing and interrupted promotion recovery is "
            f"ambiguous; inspect: {rendered}"
        )
    transaction_root = transactions[0]
    backup = transaction_root / "backup"
    if backup.is_symlink() or not backup.is_dir():
        raise ValueError(
            "destination is missing but the interrupted promotion has no "
            f"restorable backup; inspect: {transaction_root}"
        )
    physical_inventory(backup)
    inventory(backup)
    try:
        os.replace(backup, destination)
    except OSError as error:
        raise ValueError(
            f"could not restore interrupted promotion backup {backup}: {error}"
        ) from error
    try:
        shutil.rmtree(transaction_root)
    except OSError as error:
        raise ValueError(
            "restored the interrupted destination, but transaction cleanup "
            f"failed; inspect: {transaction_root}: {error}"
        ) from error
    return (transaction_root,)


def require_no_interrupted_promotion(repo_root: Path, skill: str) -> None:
    skills_root = _validate_skills_root(repo_root)
    transactions = _validated_transaction_roots(skills_root, skill)
    if transactions:
        rendered = ", ".join(str(path) for path in transactions)
        raise ValueError(
            "unfinished promotion transaction retained; run --recover only "
            f"after inspecting the reported state: {rendered}"
        )


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


def _materialize_record(record: FileRecord, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(record.data)
    destination.chmod(record.mode)


def _commit_candidate(
    *,
    candidate: Path,
    destination: Path,
    backup: Path,
    reviewed_destination_tree: dict[Path, FileRecord],
) -> None:
    try:
        os.replace(destination, backup)
        if not _same_inventory(
            physical_inventory(backup),
            reviewed_destination_tree,
        ):
            raise ValueError(
                "destination changed immediately before the swap; external "
                "changes were restored and nothing was applied"
            )
        os.replace(candidate, destination)
    except BaseException as commit_error:
        if not backup.is_dir():
            if destination.is_dir():
                raise
            raise PromotionRecoveryError(
                "promotion failed with both destination and backup missing; "
                f"inspect transaction state at {backup.parent}"
            ) from commit_error
        try:
            if destination.exists() or destination.is_symlink():
                os.replace(destination, candidate)
            os.replace(backup, destination)
        except BaseException as rollback_error:
            raise PromotionRecoveryError(
                "promotion commit and rollback both failed; "
                f"recover the original destination from {backup}: {rollback_error}"
            ) from commit_error
        raise


def apply_plan(
    plan: PromotionPlan,
    repo_files: dict[Path, FileRecord],
    live_files: dict[Path, FileRecord],
    repo_root: Path,
    live_root: Path,
    skill: str,
    include_new: bool,
    reviewed_snapshot: str,
) -> None:
    current_snapshot = review_snapshot(
        skill=skill,
        repo_files=repo_files,
        live_files=live_files,
        include_new=include_new,
    )
    if reviewed_snapshot != current_snapshot:
        raise ValueError(
            "reviewed snapshot does not match current repository and live "
            f"inventories; review {current_snapshot} before applying"
        )
    if plan.added and not include_new:
        raise ValueError("new live files require --include-new")
    if destination_is_dirty(repo_root, skill):
        raise ValueError(f"destination scope skills/{skill} is dirty; refusing --apply")
    destination_root = _validate_destination_chain(repo_root, skill)
    destination_tree = physical_inventory(destination_root)
    selected_paths = tuple(
        sorted(
            {
                *plan.modified,
                *plan.mode_changed,
                *(plan.added if include_new else ()),
            }
        )
    )
    transaction_root = Path(
        tempfile.mkdtemp(
            prefix=f".{skill}.promote-",
            dir=destination_root.parent,
        )
    )
    candidate = transaction_root / "candidate"
    backup = transaction_root / "backup"
    retain_transaction = False
    try:
        _write_transaction_marker(transaction_root, skill)
        shutil.copytree(destination_root, candidate, symlinks=True)
        staged_physical_base = physical_inventory(candidate)
        if not _same_inventory(staged_physical_base, destination_tree):
            raise ValueError(
                "destination changed while the complete replacement tree was "
                "staged; nothing was applied"
            )
        staged_base = inventory(candidate)
        if not _same_inventory(staged_base, repo_files):
            raise ValueError(
                "destination changed while the replacement tree was staged; "
                "nothing was applied"
            )
        for relative in selected_paths:
            _materialize_record(live_files[relative], candidate / relative)

        expected_files = dict(repo_files)
        for relative in selected_paths:
            expected_files[relative] = live_files[relative]
        staged_files = inventory(candidate)
        if not _same_inventory(staged_files, expected_files):
            raise ValueError(
                "staged replacement does not match the reviewed inventory; "
                "nothing was applied"
            )

        latest_repo_files = inventory(destination_root)
        latest_destination_tree = physical_inventory(destination_root)
        latest_live_files = inventory(live_root)
        latest_snapshot = review_snapshot(
            skill=skill,
            repo_files=latest_repo_files,
            live_files=latest_live_files,
            include_new=include_new,
        )
        if latest_snapshot != reviewed_snapshot:
            raise ValueError(
                "repository or live source changed while staging; nothing was "
                "applied"
            )
        if not _same_inventory(latest_destination_tree, destination_tree):
            raise ValueError(
                "destination artifacts changed while staging; nothing was applied"
            )
        if destination_is_dirty(repo_root, skill):
            raise ValueError(
                f"destination scope skills/{skill} became dirty; refusing --apply"
            )
        _validate_destination_chain(repo_root, skill)
        try:
            _commit_candidate(
                candidate=candidate,
                destination=destination_root,
                backup=backup,
                reviewed_destination_tree=destination_tree,
            )
        except PromotionRecoveryError:
            retain_transaction = True
            raise
        except OSError as error:
            raise ValueError(
                f"promotion commit failed; original destination restored: {error}"
            ) from error
        try:
            shutil.rmtree(backup)
        except OSError as error:
            retain_transaction = True
            raise ValueError(
                "promotion was applied, but the previous tree could not be "
                f"removed; recoverable backup retained at {backup}: {error}"
            ) from error
        try:
            shutil.rmtree(transaction_root)
        except OSError as error:
            retain_transaction = True
            raise ValueError(
                "promotion was applied, but its completed transaction marker "
                f"was retained at {transaction_root}; run --recover: {error}"
            ) from error
    except OSError as error:
        raise ValueError(
            f"promotion staging failed; destination was not changed: {error}"
        ) from error
    finally:
        if not retain_transaction:
            shutil.rmtree(transaction_root, ignore_errors=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--include-new", action="store_true")
    parser.add_argument("--snapshot")
    parser.add_argument("--repo-root")
    parser.add_argument("--live-root")
    args = parser.parse_args(argv)
    if args.skill not in ALLOWED_SKILLS:
        parser.error(f"skill {args.skill!r} is not allowed")
    if args.apply and not args.snapshot:
        parser.error("--apply requires the --snapshot printed by a reviewed preview")
    if args.snapshot and not args.apply:
        parser.error("--snapshot requires --apply")
    if args.recover and (args.apply or args.snapshot or args.include_new):
        parser.error("--recover cannot be combined with apply or preview options")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = Path(args.repo_root).absolute() if args.repo_root else Path(__file__).resolve().parents[1]
    live_root = Path(args.live_root).expanduser().absolute() if args.live_root else Path(
        os.environ.get("AGENTS_SKILLS_ROOT", "~/.agents/skills")
    ).expanduser().absolute()
    try:
        if args.recover:
            recovered = recover_interrupted_promotion(repo_root, args.skill)
            if not recovered:
                print(f"No interrupted promotion found for {args.skill}.")
            else:
                rendered = ", ".join(str(path) for path in recovered)
                print(f"Recovered interrupted promotion state from {rendered}.")
            return 0
        require_no_interrupted_promotion(repo_root, args.skill)
        if live_root.is_symlink():
            raise ValueError(f"live root must not be a symlink: {live_root}")
        destination_root = _validate_destination_chain(repo_root, args.skill)
        repo_files = inventory(destination_root)
        live_files = inventory(live_root / args.skill)
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    plan = classify(repo_files, live_files)
    snapshot = review_snapshot(
        skill=args.skill,
        repo_files=repo_files,
        live_files=live_files,
        include_new=args.include_new,
    )
    if not (plan.modified or plan.added or plan.mode_changed or plan.repository_only):
        print(f"No drift: {args.skill} is identical.")
        print(f"Review snapshot: {snapshot}")
        if args.apply and args.snapshot != snapshot:
            print(
                "error: reviewed snapshot does not match current repository "
                "and live inventories",
                file=sys.stderr,
            )
            return 2
        return 0
    print(f"Drift detected for {args.skill}.")
    print(render_plan(plan, repo_files, live_files), end="")
    print(f"Review snapshot: {snapshot}")
    if args.apply:
        try:
            apply_plan(
                plan,
                repo_files,
                live_files,
                repo_root,
                live_root / args.skill,
                args.skill,
                args.include_new,
                args.snapshot,
            )
        except ValueError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        print(
            f"Applied reviewed snapshot {snapshot}. Nothing was staged or published."
        )
        return 0
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
