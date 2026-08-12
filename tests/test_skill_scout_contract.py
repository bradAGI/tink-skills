"""Contract tests for Skill Scout's read-only candidate inspection boundary."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / "skills" / "skill-scout" / "references" / "scouting-workflow.md"
MALICIOUS_CANDIDATE = REPO_ROOT / "tests" / "fixtures" / "skill-scout-malicious-candidate"


class SkillScoutContractTests(unittest.TestCase):
    def test_candidate_helpers_are_inert_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "executed"
            with patch.dict(os.environ, {"SKILL_SCOUT_EXECUTION_MARKER": str(marker)}):
                workflow = WORKFLOW.read_text()
                helper = (MALICIOUS_CANDIDATE / "repo-brief" / "scripts" / "repo_brief.mjs").read_text()

        self.assertIn("writeFileSync", helper)
        self.assertFalse(marker.exists(), "candidate-owned helper was executed")
        self.assertIn("already-loaded,", workflow)
        self.assertIn("identity-verified `repo-brief` capability", workflow)
        self.assertIn("Never resolve or execute a helper from", workflow)
        self.assertIn("the candidate, the current repository", workflow)
        self.assertNotIn("then in the current repository", workflow)
        self.assertNotIn("node <resolved-script>", workflow)


if __name__ == "__main__":
    unittest.main()
