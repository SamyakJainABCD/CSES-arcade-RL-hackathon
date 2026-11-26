"""Coding-agent benchmark graders accept the reference solutions and reject the plausible wrong ones."""
import os
import shutil
import tempfile
import unittest

from benchmarks.coding_agent.common import HERE, build_workspace
from benchmarks.coding_agent.grade import grade


def workspace_with(task: str, files: dict) -> str:
    """A prepared workspace with solution files copied over: {workspace path: source path}."""
    path = tempfile.mkdtemp(prefix=f"bench_{task}_")
    build_workspace(task, path)
    for dst, src in files.items():
        target = os.path.join(path, dst)
        if os.path.isdir(src):
            shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(src, target)
        else:
            shutil.copy2(src, target)
    return path


def sol(*parts: str) -> str:
    return os.path.join(HERE, *parts)


class GraderTest(unittest.TestCase):
    def test_t1(self):
        self.assertTrue(grade("T1", workspace_with("T1", {"belief.py": sol("solutions", "T1_belief", "belief.py")}))["passed"])
        wrong = grade("T1", workspace_with("T1", {"belief.py": sol("wrong_solutions", "T1_naive", "belief.py")}))
        self.assertFalse(wrong["passed"])
        self.assertGreater(wrong["wrong"], 0)
        self.assertFalse(grade("T1", workspace_with("T1", {}))["passed"])  # the stub

    def test_t1_rejects_edits_to_the_engine(self):
        ws = workspace_with("T1", {"belief.py": sol("solutions", "T1_belief", "belief.py")})
        with open(os.path.join(ws, "game_API.py"), "a") as f:
            f.write("\n# shuffle the gun instead\n")
        result = grade("T1", ws)
        self.assertFalse(result["passed"])
        self.assertEqual(result["tampered"], ["game_API.py"])

    def test_t2(self):
        self.assertTrue(grade("T2", workspace_with("T2", {"game_API.py": sol("solutions", "T2_bugfix", "game_API.py")}))["passed"])
        wrong = grade("T2", workspace_with("T2", {"game_API.py": sol("wrong_solutions", "T2_upper_bound_only", "game_API.py")}))
        self.assertFalse(wrong["passed"])
        self.assertIn("direct target=-1", wrong["failed_checks"])
        self.assertEqual(wrong["regressions"], [])

    def test_t3(self):
        self.assertTrue(grade("T3", workspace_with("T3", {"my_bot": sol("solutions", "T3_bot", "my_bot")}))["passed"])
        self.assertFalse(grade("T3", workspace_with("T3", {"my_bot": sol("wrong_solutions", "T3_greedy", "my_bot")}))["passed"])


if __name__ == "__main__":
    unittest.main()
