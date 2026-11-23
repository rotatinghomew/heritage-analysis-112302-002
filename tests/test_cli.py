"""命令行冒烟测试。"""
import contextlib
import io
from pathlib import Path
import unittest

from evidencetool.__main__ import main

ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(["--repo", str(ROOT), *args])
    return code, out.getvalue()


class CliTests(unittest.TestCase):
    def test_summary(self):
        code, out = run_cli("summary")
        self.assertEqual(code, 0)
        self.assertIn("仍成立的整图解释 2 组", out)

    def test_families_shows_dependency_risk(self):
        code, out = run_cli("families")
        self.assertEqual(code, 0)
        self.assertIn("SURV-3 ↔ ARCH-2", out)
        self.assertIn("低于手册标准", out)

    def test_sets_warns_never_simultaneous(self):
        code, out = run_cli("sets")
        self.assertEqual(code, 0)
        self.assertIn("从未同时出现", out)
        self.assertIn("图层依据", out)

    def test_labels_verdicts(self):
        code, out = run_cli("labels")
        self.assertEqual(code, 0)
        self.assertIn("可继续使用", out)
        self.assertIn("需修改后方可签发", out)

    def test_impact_marks_replacements(self):
        code, out = run_cli("impact")
        self.assertEqual(code, 0)
        self.assertIn("必须更换", out)
        self.assertIn("可继续使用", out)
        self.assertIn("图层缺口", out)

    def test_verify_passes_on_committed_repo(self):
        code, out = run_cli("verify")
        self.assertEqual(code, 0)
        self.assertIn("通过", out)

    def test_as_issued_returns_snapshot(self):
        code, out = run_cli("as-issued", "L1", "1")
        self.assertEqual(code, 0)
        self.assertIn("巡展方实际收到的内容", out)
        self.assertIn("content_hash", out)


if __name__ == "__main__":
    unittest.main()
