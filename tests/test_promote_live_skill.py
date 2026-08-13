"""Contract tests for the guarded live-skill promotion command."""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "promote_live_skill.py"
SNAPSHOT_PATTERN = re.compile(r"Review snapshot: (sha256:[0-9a-f]{64})")
PROMOTION_SPEC = importlib.util.spec_from_file_location(
    "tink_promote_live_skill",
    SCRIPT,
)
assert PROMOTION_SPEC is not None and PROMOTION_SPEC.loader is not None
promotion = importlib.util.module_from_spec(PROMOTION_SPEC)
sys.modules[PROMOTION_SPEC.name] = promotion
PROMOTION_SPEC.loader.exec_module(promotion)


class PromotionToolTests(unittest.TestCase):
    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def reviewed_snapshot(
        self,
        *,
        repo: Path,
        live: Path,
        include_new: bool = False,
    ) -> str:
        args = [
            "--skill",
            "skill-scout",
            "--repo-root",
            str(repo),
            "--live-root",
            str(live),
        ]
        if include_new:
            args.append("--include-new")
        result = self.run_tool(*args)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        match = SNAPSHOT_PATTERN.search(result.stdout)
        self.assertIsNotNone(match, result.stdout)
        return match.group(1)

    def apply_reviewed(
        self,
        *,
        repo: Path,
        live: Path,
        include_new: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        snapshot = self.reviewed_snapshot(
            repo=repo,
            live=live,
            include_new=include_new,
        )
        args = [
            "--skill",
            "skill-scout",
            "--repo-root",
            str(repo),
            "--live-root",
            str(live),
            "--apply",
            "--snapshot",
            snapshot,
        ]
        if include_new:
            args.append("--include-new")
        return self.run_tool(*args)

    def init_git_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test User"], check=True)

    def test_rejects_unknown_skill(self) -> None:
        result = self.run_tool("--skill", "not-a-skill")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed", result.stderr)

    def test_apply_requires_a_reviewed_snapshot(self) -> None:
        result = self.run_tool("--skill", "skill-scout", "--apply")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--apply requires", result.stderr)

    def test_identical_tree_returns_zero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (repo / "skills" / "skill-scout", live / "skill-scout"):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("# Skill\n")
            result = self.run_tool(
                "--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live)
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("No drift", result.stdout)

    def test_triangulate_me_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (
                repo / "skills" / "triangulate-me",
                live / "triangulate-me",
            ):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("# Triangulate Me\n")
            result = self.run_tool(
                "--skill",
                "triangulate-me",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
        self.assertEqual(result.returncode, 0)
        self.assertIn("No drift", result.stdout)

    def test_changed_file_returns_one_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root, text in (
                (repo / "skills" / "skill-scout", "old\n"),
                (live / "skill-scout", "new\n"),
            ):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text(text)
            result = self.run_tool(
                "--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live)
            )
            destination = (repo / "skills" / "skill-scout" / "SKILL.md").read_text()
        self.assertEqual(result.returncode, 1)
        self.assertIn("---", result.stdout)
        self.assertEqual(destination, "old\n")

    def test_generated_files_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (repo / "skills" / "skill-scout", live / "skill-scout"):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("same\n")
            (live / "skill-scout" / "__pycache__").mkdir()
            (live / "skill-scout" / "__pycache__" / "run.pyc").write_bytes(b"cache")
            result = self.run_tool("--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live))
        self.assertEqual(result.returncode, 0)

    def test_live_root_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            live_target, live_link = root / "live-target", root / "live-link"
            (repo / "skills" / "skill-scout").mkdir(parents=True)
            (repo / "skills" / "skill-scout" / "SKILL.md").write_text("same\n")
            (live_target / "skill-scout").mkdir(parents=True)
            (live_target / "skill-scout" / "SKILL.md").write_text("same\n")
            live_link.symlink_to(live_target, target_is_directory=True)
            result = self.run_tool("--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live_link))
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlink", result.stderr)

    def test_nested_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (repo / "skills" / "skill-scout", live / "skill-scout"):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("same\n")
            target = root / "target"
            target.write_text("target\n")
            (live / "skill-scout" / "scripts").mkdir()
            (live / "skill-scout" / "scripts" / "linked.py").symlink_to(target)
            result = self.run_tool("--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live))
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlinked entry", result.stderr)

    def test_symlink_inside_excluded_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (
                repo / "skills" / "skill-scout",
                live / "skill-scout",
            ):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("same\n")
            target = root / "target"
            target.write_text("target\n")
            excluded = live / "skill-scout" / "__pycache__"
            excluded.mkdir()
            (excluded / "linked.pyc").symlink_to(target)
            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlinked entry", result.stderr)

    def test_path_outside_allowed_skill_layout_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (repo / "skills" / "skill-scout", live / "skill-scout"):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("same\n")
            (live / "skill-scout" / "notes.txt").write_text("not publishable\n")
            result = self.run_tool("--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live))
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the allowed", result.stderr)

    def test_allowed_directory_name_must_be_a_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (
                repo / "skills" / "skill-scout",
                live / "skill-scout",
            ):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("same\n")
            (live / "skill-scout" / "scripts").write_text("not a directory\n")
            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be a directory", result.stderr)

    def test_unapproved_empty_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (
                repo / "skills" / "skill-scout",
                live / "skill-scout",
            ):
                skill_root.mkdir(parents=True)
                (skill_root / "SKILL.md").write_text("same\n")
            (live / "skill-scout" / "scratch").mkdir()
            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the allowed", result.stderr)

    def test_apply_refuses_dirty_destination_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            (destination / "SKILL.md").write_text("old\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            (destination / "SKILL.md").write_text("dirty\n")
            (live / "skill-scout").mkdir(parents=True)
            (live / "skill-scout" / "SKILL.md").write_text("live\n")
            result = self.apply_reviewed(repo=repo, live=live)
        self.assertEqual(result.returncode, 2)
        self.assertIn("dirty", result.stderr)

    def test_apply_copies_changed_file_and_mode(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout" / "scripts"
            source = live / "skill-scout" / "scripts"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            (repo / "skills" / "skill-scout" / "SKILL.md").write_text("# Skill\n")
            (live / "skill-scout" / "SKILL.md").write_text("# Skill\n")
            destination_file, source_file = destination / "run.py", source / "run.py"
            destination_file.write_text("old\n")
            source_file.write_text("new\n")
            source_file.chmod(0o755)
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            result = self.apply_reviewed(repo=repo, live=live)
            copied = destination_file.read_text()
            executable = bool(destination_file.stat().st_mode & 0o111)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(copied, "new\n")
        self.assertTrue(executable)
        self.assertRegex(
            result.stdout,
            r"Applied reviewed snapshot sha256:[0-9a-f]{64}",
        )

    def test_dry_run_reports_mode_change_alongside_content_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            for skill_root in (repo / "skills" / "skill-scout", live / "skill-scout"):
                skill_root.mkdir(parents=True)
            repo_file = repo / "skills" / "skill-scout" / "SKILL.md"
            live_file = live / "skill-scout" / "SKILL.md"
            repo_file.write_text("old\n")
            live_file.write_text("new\n")
            live_file.chmod(0o755)
            result = self.run_tool("--skill", "skill-scout", "--repo-root", str(repo), "--live-root", str(live))
        self.assertEqual(result.returncode, 1)
        self.assertIn("mode changed: SKILL.md (0644 -> 0755)", result.stdout)

    def test_render_uses_the_inventoried_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo_skill = root / "repo" / "skills" / "skill-scout"
            live_skill = root / "live" / "skill-scout"
            repo_skill.mkdir(parents=True)
            live_skill.mkdir(parents=True)
            repo_skill.joinpath("SKILL.md").write_text("old\n")
            live_file = live_skill / "SKILL.md"
            live_file.write_text("reviewed\n")
            repo_files = promotion.inventory(repo_skill)
            live_files = promotion.inventory(live_skill)
            plan = promotion.classify(repo_files, live_files)

            live_file.write_text("changed after inventory\n")
            rendered = promotion.render_plan(plan, repo_files, live_files)

        self.assertIn("+reviewed", rendered)
        self.assertNotIn("changed after inventory", rendered)

    def test_source_content_drift_rejects_the_reviewed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            source_file = source / "SKILL.md"
            source_file.write_text("reviewed\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            snapshot = self.reviewed_snapshot(repo=repo, live=live)
            source_file.write_text("changed after review\n")

            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
                "--apply",
                "--snapshot",
                snapshot,
            )

            self.assertEqual(destination.joinpath("SKILL.md").read_text(), "old\n")
        self.assertEqual(result.returncode, 2)
        self.assertIn("reviewed snapshot does not match", result.stderr)

    def test_source_mode_drift_rejects_the_reviewed_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("same\n")
            source_file = source / "SKILL.md"
            source_file.write_text("same\n")
            source_file.chmod(0o755)
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            snapshot = self.reviewed_snapshot(repo=repo, live=live)
            source_file.chmod(0o700)

            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
                "--apply",
                "--snapshot",
                snapshot,
            )

            destination_mode = destination.joinpath("SKILL.md").stat().st_mode & 0o777
        self.assertEqual(result.returncode, 2)
        self.assertIn("reviewed snapshot does not match", result.stderr)
        self.assertEqual(destination_mode, 0o644)

    def test_new_file_requires_include_new(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("# Skill\n")
            (live / "skill-scout" / "scripts").mkdir(parents=True)
            (live / "skill-scout" / "SKILL.md").write_text("# Skill\n")
            (live / "skill-scout" / "scripts" / "new.py").write_text("print('new')\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            snapshot = self.reviewed_snapshot(repo=repo, live=live)
            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--apply",
                "--snapshot",
                snapshot,
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
            created = (destination / "scripts" / "new.py").exists()
        self.assertEqual(result.returncode, 2)
        self.assertIn("--include-new", result.stderr)
        self.assertFalse(created)

    def test_new_text_file_preview_shows_complete_diff(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("# Skill\n")
            source = live / "skill-scout"
            source.joinpath("scripts").mkdir(parents=True)
            source.joinpath("SKILL.md").write_text("# Skill\n")
            source.joinpath("scripts", "new.py").write_text("print('review me')\n")
            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("new file mode: scripts/new.py (0644)", result.stdout)
        self.assertIn("--- /dev/null", result.stdout)
        self.assertIn("+++ live/scripts/new.py", result.stdout)
        self.assertIn("+print('review me')", result.stdout)

    def test_include_new_applies_only_the_reviewed_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.joinpath("scripts").mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("# Skill\n")
            source.joinpath("SKILL.md").write_text("# Skill\n")
            source.joinpath("scripts", "new.py").write_text("print('new')\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )

            result = self.apply_reviewed(
                repo=repo,
                live=live,
                include_new=True,
            )

            created = destination.joinpath("scripts", "new.py").read_text()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(created, "print('new')\n")

    def test_apply_never_deletes_repo_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("# Skill\n")
            destination.joinpath(".DS_Store").write_text("keep local cache\n")
            destination.joinpath("references").mkdir()
            destination.joinpath("references", "kept.md").write_text("keep\n")
            (live / "skill-scout").mkdir(parents=True)
            (live / "skill-scout" / "SKILL.md").write_text("changed\n")
            (live / "skill-scout" / ".DS_Store").write_text("ignore live cache\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            result = self.apply_reviewed(repo=repo, live=live)
            preserved = destination.joinpath("references", "kept.md").read_text()
            local_cache = destination.joinpath(".DS_Store").read_text()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(preserved, "keep\n")
        self.assertEqual(local_cache, "keep local cache\n")

    def test_apply_does_not_stage_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            (live / "skill-scout").mkdir(parents=True)
            (live / "skill-scout" / "SKILL.md").write_text("new\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            result = self.apply_reviewed(repo=repo, live=live)
            status = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True
            ).stdout
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(status.startswith(" M skills/skill-scout/SKILL.md"), status)

    def test_staging_failure_leaves_the_destination_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.joinpath("scripts").mkdir(parents=True)
            source.joinpath("scripts").mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old skill\n")
            destination.joinpath("scripts", "run.py").write_text("old script\n")
            source.joinpath("SKILL.md").write_text("new skill\n")
            source.joinpath("scripts", "run.py").write_text("new script\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            repo_files = promotion.inventory(destination)
            live_files = promotion.inventory(source)
            plan = promotion.classify(repo_files, live_files)
            snapshot = promotion.review_snapshot(
                skill="skill-scout",
                repo_files=repo_files,
                live_files=live_files,
                include_new=False,
            )
            materialize = promotion._materialize_record
            calls = 0

            def fail_second_copy(record: promotion.FileRecord, target: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected staging failure")
                materialize(record, target)

            with (
                patch.object(
                    promotion,
                    "_materialize_record",
                    side_effect=fail_second_copy,
                ),
                self.assertRaisesRegex(ValueError, "staging failed"),
            ):
                promotion.apply_plan(
                    plan=plan,
                    repo_files=repo_files,
                    live_files=live_files,
                    repo_root=repo,
                    live_root=source,
                    skill="skill-scout",
                    include_new=False,
                    reviewed_snapshot=snapshot,
                )

            self.assertTrue(
                promotion._same_inventory(
                    promotion.inventory(destination),
                    repo_files,
                )
            )
            self.assertEqual(
                list((repo / "skills").glob(".skill-scout.promote-*")),
                [],
            )

    def test_failed_commit_restores_the_complete_old_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.joinpath("references").mkdir(parents=True)
            source.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            destination.joinpath("references", "kept.md").write_text("keep\n")
            source.joinpath("SKILL.md").write_text("new\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            repo_files = promotion.inventory(destination)
            live_files = promotion.inventory(source)
            plan = promotion.classify(repo_files, live_files)
            snapshot = promotion.review_snapshot(
                skill="skill-scout",
                repo_files=repo_files,
                live_files=live_files,
                include_new=False,
            )
            replace = promotion.os.replace
            calls = 0

            def fail_candidate_swap(source_path: Path, target_path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected commit failure")
                replace(source_path, target_path)

            with (
                patch.object(
                    promotion.os,
                    "replace",
                    side_effect=fail_candidate_swap,
                ),
                self.assertRaisesRegex(ValueError, "original destination restored"),
            ):
                promotion.apply_plan(
                    plan=plan,
                    repo_files=repo_files,
                    live_files=live_files,
                    repo_root=repo,
                    live_root=source,
                    skill="skill-scout",
                    include_new=False,
                    reviewed_snapshot=snapshot,
                )

            self.assertTrue(
                promotion._same_inventory(
                    promotion.inventory(destination),
                    repo_files,
                )
            )
            self.assertEqual(
                destination.joinpath("references", "kept.md").read_text(),
                "keep\n",
            )
            self.assertEqual(
                list((repo / "skills").glob(".skill-scout.promote-*")),
                [],
            )

    def test_last_moment_destination_change_is_restored_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            destination_file = destination / "SKILL.md"
            destination_file.write_text("old\n")
            source.joinpath("SKILL.md").write_text("new\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            repo_files = promotion.inventory(destination)
            live_files = promotion.inventory(source)
            plan = promotion.classify(repo_files, live_files)
            snapshot = promotion.review_snapshot(
                skill="skill-scout",
                repo_files=repo_files,
                live_files=live_files,
                include_new=False,
            )
            replace = promotion.os.replace
            calls = 0

            def mutate_before_first_swap(source_path: Path, target_path: Path) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    destination_file.write_text("external edit\n")
                replace(source_path, target_path)

            with (
                patch.object(
                    promotion.os,
                    "replace",
                    side_effect=mutate_before_first_swap,
                ),
                self.assertRaisesRegex(ValueError, "external changes were restored"),
            ):
                promotion.apply_plan(
                    plan=plan,
                    repo_files=repo_files,
                    live_files=live_files,
                    repo_root=repo,
                    live_root=source,
                    skill="skill-scout",
                    include_new=False,
                    reviewed_snapshot=snapshot,
                )

            self.assertEqual(destination_file.read_text(), "external edit\n")
            self.assertEqual(
                list((repo / "skills").glob(".skill-scout.promote-*")),
                [],
            )

    def test_last_moment_excluded_change_is_restored_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            excluded_file = destination / ".DS_Store"
            excluded_file.write_text("old excluded\n")
            source.joinpath("SKILL.md").write_text("new\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            repo_files = promotion.inventory(destination)
            live_files = promotion.inventory(source)
            plan = promotion.classify(repo_files, live_files)
            snapshot = promotion.review_snapshot(
                skill="skill-scout",
                repo_files=repo_files,
                live_files=live_files,
                include_new=False,
            )
            replace = promotion.os.replace
            calls = 0

            def mutate_excluded_before_swap(
                source_path: Path,
                target_path: Path,
            ) -> None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    excluded_file.write_text("external excluded edit\n")
                replace(source_path, target_path)

            with (
                patch.object(
                    promotion.os,
                    "replace",
                    side_effect=mutate_excluded_before_swap,
                ),
                self.assertRaisesRegex(ValueError, "external changes were restored"),
            ):
                promotion.apply_plan(
                    plan=plan,
                    repo_files=repo_files,
                    live_files=live_files,
                    repo_root=repo,
                    live_root=source,
                    skill="skill-scout",
                    include_new=False,
                    reviewed_snapshot=snapshot,
                )

            self.assertEqual(excluded_file.read_text(), "external excluded edit\n")

    def test_completed_marker_cleanup_is_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            source.joinpath("SKILL.md").write_text("new\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            repo_files = promotion.inventory(destination)
            live_files = promotion.inventory(source)
            plan = promotion.classify(repo_files, live_files)
            snapshot = promotion.review_snapshot(
                skill="skill-scout",
                repo_files=repo_files,
                live_files=live_files,
                include_new=False,
            )
            rmtree = promotion.shutil.rmtree

            def fail_marker_cleanup(path: Path, *args: object, **kwargs: object) -> None:
                target = Path(path)
                if target.name.startswith(".skill-scout.promote-"):
                    raise OSError("injected marker cleanup failure")
                rmtree(path, *args, **kwargs)

            with (
                patch.object(
                    promotion.shutil,
                    "rmtree",
                    side_effect=fail_marker_cleanup,
                ),
                self.assertRaisesRegex(ValueError, "completed transaction marker"),
            ):
                promotion.apply_plan(
                    plan=plan,
                    repo_files=repo_files,
                    live_files=live_files,
                    repo_root=repo,
                    live_root=source,
                    skill="skill-scout",
                    include_new=False,
                    reviewed_snapshot=snapshot,
                )

            transactions = list(
                (repo / "skills").glob(".skill-scout.promote-*")
            )
            self.assertEqual(len(transactions), 1)
            self.assertEqual(
                {path.name for path in transactions[0].iterdir()},
                {"transaction.json"},
            )
            self.assertEqual(destination.joinpath("SKILL.md").read_text(), "new\n")

            recovered = promotion.recover_interrupted_promotion(
                repo,
                "skill-scout",
            )

            self.assertEqual(recovered, tuple(transactions))
            self.assertFalse(transactions[0].exists())
            self.assertEqual(destination.joinpath("SKILL.md").read_text(), "new\n")

    def test_keyboard_interrupt_after_first_move_restores_old_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            source = live / "skill-scout"
            destination.mkdir(parents=True)
            source.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            source.joinpath("SKILL.md").write_text("new\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "initial"],
                check=True,
            )
            repo_files = promotion.inventory(destination)
            live_files = promotion.inventory(source)
            plan = promotion.classify(repo_files, live_files)
            snapshot = promotion.review_snapshot(
                skill="skill-scout",
                repo_files=repo_files,
                live_files=live_files,
                include_new=False,
            )
            replace = promotion.os.replace
            calls = 0

            def interrupt_after_first_move(
                source_path: Path,
                target_path: Path,
            ) -> None:
                nonlocal calls
                calls += 1
                replace(source_path, target_path)
                if calls == 1:
                    raise KeyboardInterrupt

            with (
                patch.object(
                    promotion.os,
                    "replace",
                    side_effect=interrupt_after_first_move,
                ),
                self.assertRaises(KeyboardInterrupt),
            ):
                promotion.apply_plan(
                    plan=plan,
                    repo_files=repo_files,
                    live_files=live_files,
                    repo_root=repo,
                    live_root=source,
                    skill="skill-scout",
                    include_new=False,
                    reviewed_snapshot=snapshot,
                )

            self.assertEqual(destination.joinpath("SKILL.md").read_text(), "old\n")
            self.assertEqual(
                list((repo / "skills").glob(".skill-scout.promote-*")),
                [],
            )

    def test_next_run_recovers_an_interrupted_missing_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("old\n")
            live.joinpath("skill-scout").mkdir(parents=True)
            live.joinpath("skill-scout", "SKILL.md").write_text("old\n")
            transaction = repo / "skills" / ".skill-scout.promote-interrupted"
            transaction.mkdir()
            promotion._write_transaction_marker(transaction, "skill-scout")
            transaction.joinpath("candidate").mkdir()
            transaction.joinpath("candidate", "SKILL.md").write_text("new\n")
            promotion.os.replace(destination, transaction / "backup")

            preview = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )
            self.assertFalse(destination.exists())
            self.assertTrue(transaction.is_dir())

            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--recover",
            )

            restored = destination.joinpath("SKILL.md").read_text()
        self.assertEqual(preview.returncode, 2)
        self.assertIn("run --recover", preview.stderr)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Recovered interrupted promotion", result.stdout)
        self.assertEqual(restored, "old\n")

    def test_recovery_rejects_a_nested_symlink_in_the_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            skills_root = repo / "skills"
            transaction = skills_root / ".skill-scout.promote-interrupted"
            backup = transaction / "backup"
            backup.joinpath("references").mkdir(parents=True)
            backup.joinpath("SKILL.md").write_text("old\n")
            target = root / "outside"
            target.write_text("outside\n")
            backup.joinpath("references", "linked.md").symlink_to(target)
            promotion._write_transaction_marker(transaction, "skill-scout")

            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--recover",
            )

            self.assertFalse(skills_root.joinpath("skill-scout").exists())
            self.assertTrue(backup.is_dir())
        self.assertEqual(result.returncode, 2)
        self.assertIn("symlinked entry is not allowed", result.stderr)

    def test_pending_transaction_with_destination_is_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("current\n")
            live.joinpath("skill-scout").mkdir(parents=True)
            live.joinpath("skill-scout", "SKILL.md").write_text("current\n")
            transaction = repo / "skills" / ".skill-scout.promote-interrupted"
            transaction.mkdir()
            promotion._write_transaction_marker(transaction, "skill-scout")
            transaction.joinpath("candidate").mkdir()
            transaction.joinpath("candidate", "SKILL.md").write_text("candidate\n")

            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--recover",
            )

            self.assertTrue(transaction.is_dir())
            current = destination.joinpath("SKILL.md").read_text()
        self.assertEqual(result.returncode, 2)
        self.assertIn("unfinished promotion transaction retained", result.stderr)
        self.assertEqual(current, "current\n")

    def test_symlinked_repository_skills_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            real_skills = root / "real-skills"
            real_skills.joinpath("skill-scout").mkdir(parents=True)
            real_skills.joinpath("skill-scout", "SKILL.md").write_text("old\n")
            repo.mkdir()
            repo.joinpath("skills").symlink_to(real_skills, target_is_directory=True)
            live.joinpath("skill-scout").mkdir(parents=True)
            live.joinpath("skill-scout", "SKILL.md").write_text("new\n")

            result = self.run_tool(
                "--skill",
                "skill-scout",
                "--repo-root",
                str(repo),
                "--live-root",
                str(live),
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("repository skills root must not be a symlink", result.stderr)


if __name__ == "__main__":
    unittest.main()
