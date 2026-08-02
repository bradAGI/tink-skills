"""Contract tests for the guarded live-skill promotion command."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "tools" / "promote_live_skill.py"


class PromotionToolTests(unittest.TestCase):
    def run_tool(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), *args],
            text=True,
            capture_output=True,
            check=False,
        )

    def init_git_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
        subprocess.run(["git", "-C", str(root), "config", "user.name", "Test User"], check=True)

    def test_rejects_unknown_skill(self) -> None:
        result = self.run_tool("--skill", "not-a-skill")
        self.assertEqual(result.returncode, 2)
        self.assertIn("not allowed", result.stderr)

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
            result = self.run_tool("--skill", "skill-scout", "--apply", "--repo-root", str(repo), "--live-root", str(live))
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
            result = self.run_tool("--skill", "skill-scout", "--apply", "--repo-root", str(repo), "--live-root", str(live))
            copied = destination_file.read_text()
            executable = bool(destination_file.stat().st_mode & 0o111)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(copied, "new\n")
        self.assertTrue(executable)

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
        self.assertIn("mode changed: SKILL.md", result.stdout)

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
            result = self.run_tool("--skill", "skill-scout", "--apply", "--repo-root", str(repo), "--live-root", str(live))
            created = (destination / "scripts" / "new.py").exists()
        self.assertEqual(result.returncode, 2)
        self.assertIn("--include-new", result.stderr)
        self.assertFalse(created)

    def test_apply_never_deletes_repo_only_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo, live = root / "repo", root / "live"
            destination = repo / "skills" / "skill-scout"
            destination.mkdir(parents=True)
            destination.joinpath("SKILL.md").write_text("# Skill\n")
            destination.joinpath("references").mkdir()
            destination.joinpath("references", "kept.md").write_text("keep\n")
            (live / "skill-scout").mkdir(parents=True)
            (live / "skill-scout" / "SKILL.md").write_text("changed\n")
            self.init_git_repo(repo)
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "initial"], check=True)
            result = self.run_tool("--skill", "skill-scout", "--apply", "--repo-root", str(repo), "--live-root", str(live))
            preserved = destination.joinpath("references", "kept.md").read_text()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(preserved, "keep\n")

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
            result = self.run_tool("--skill", "skill-scout", "--apply", "--repo-root", str(repo), "--live-root", str(live))
            status = subprocess.run(
                ["git", "-C", str(repo), "status", "--porcelain"], text=True, capture_output=True, check=True
            ).stdout
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(status.startswith(" M skills/skill-scout/SKILL.md"), status)


if __name__ == "__main__":
    unittest.main()
