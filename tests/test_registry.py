"""签发登记测试：快照、回查、防冒充。"""
import csv
import shutil
import tempfile
from pathlib import Path
import unittest

from evidencetool.analysis import analyze
from evidencetool.loader import load_dataset
from evidencetool.registry import as_issued, backfill_snapshots, issue, verify

ROOT = Path(__file__).resolve().parents[1]

PHASES = "phase,start,end\nearly,1600,1699\nlate,1700,1799\n"
EVIDENCE = (
    "record,source,parent,object,phase,claim,relation,year,access\n"
    "A1,SA,SA,roof,early,supports,independent,1650,research\n"
    "A2,SB,SB,roof,early,supports,independent,1660,exhibition\n"
)
INTERPS = "interpretation,object,phase,requires,conflicts\nJ1,roof,early,A1,\n"
LABELS = (
    "label,version,status,issued_to,issued_on,supersedes\n"
    "K1,1,approved,,,\n"
    "K2,1,approved,,,\n"
)
STATEMENTS = (
    "label,version,statement,group,kind,interpretation,text,image_source,licensee,display_scope,cites\n"
    "K1,1,T1,,certainty,J1,屋顶为早期遗构,,筹备厅,展厅图文,A1;A2\n"
    "K2,1,T2,,certainty,J1,屋顶为早期遗构,SA,,,A1\n"
)


def make_repo(base: Path) -> Path:
    fixtures = base / "fixtures"
    fixtures.mkdir(parents=True)
    (fixtures / "phases.csv").write_text(PHASES, encoding="utf-8")
    (fixtures / "evidence.csv").write_text(EVIDENCE, encoding="utf-8")
    (fixtures / "interps.csv").write_text(INTERPS, encoding="utf-8")
    (fixtures / "labels.csv").write_text(LABELS, encoding="utf-8")
    (fixtures / "statements.csv").write_text(STATEMENTS, encoding="utf-8")
    return base


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)
        self.repo = make_repo(self.tmp / "repo")
        self.dataset = load_dataset(self.repo / "fixtures")
        self.analysis = analyze(self.dataset)

    def reload(self):
        self.dataset = load_dataset(self.repo / "fixtures")
        self.analysis = analyze(self.dataset)

    def test_issue_writes_snapshot_and_updates_register(self):
        path, problems = issue(self.repo, self.dataset, self.analysis, "K1", "1", "巡展方丙", "2026-07-01")
        self.assertEqual(problems, [])
        self.assertTrue(path.exists())
        self.reload()
        self.assertEqual(verify(self.repo, self.dataset), [])
        docs = as_issued(self.repo, "K1", "1")
        self.assertEqual(docs[0]["issued_to"], "巡展方丙")

    def test_issue_refuses_label_with_problems(self):
        # K2 引用了仅供馆内研究的 SA 图像且缺许可信息
        path, problems = issue(self.repo, self.dataset, self.analysis, "K2", "1", "巡展方丙", "2026-07-01")
        self.assertIsNone(path)
        self.assertTrue(any("拒绝签发" in p for p in problems))

    def test_issued_version_cannot_be_issued_again(self):
        issue(self.repo, self.dataset, self.analysis, "K1", "1", "巡展方丙", "2026-07-01")
        self.reload()
        path, problems = issue(self.repo, self.dataset, self.analysis, "K1", "1", "巡展方丁", "2026-08-01")
        self.assertIsNone(path)
        self.assertTrue(any("已签发" in p for p in problems))

    def test_tampering_with_issued_content_is_detected(self):
        issue(self.repo, self.dataset, self.analysis, "K1", "1", "巡展方丙", "2026-07-01")
        # 改正旧稿：直接改写已签发版本的语句（冒充巡展方收到的内容）
        statements_file = self.repo / "fixtures" / "statements.csv"
        text = statements_file.read_text(encoding="utf-8")
        statements_file.write_text(text.replace("屋顶为早期遗构", "屋顶为晚期遗构", 1), encoding="utf-8")
        self.reload()
        problems = verify(self.repo, self.dataset)
        self.assertTrue(any("冒充" in p for p in problems))
        # 但快照里仍可按原内容回查
        docs = as_issued(self.repo, "K1", "1")
        self.assertEqual(docs[0]["statements"][0]["text"], "屋顶为早期遗构")

    def test_correction_as_new_version_does_not_break_verify(self):
        issue(self.repo, self.dataset, self.analysis, "K1", "1", "巡展方丙", "2026-07-01")
        # 正确的做法：另起新版本
        with (self.repo / "fixtures" / "labels.csv").open("a", encoding="utf-8", newline="") as fh:
            fh.write("K1,2,draft,,,1\n")
        with (self.repo / "fixtures" / "statements.csv").open("a", encoding="utf-8", newline="") as fh:
            fh.write("K1,2,T3,,certainty,J1,屋顶为早期遗构（改）,,筹备厅,展厅图文,A1;A2\n")
        self.reload()
        self.assertEqual(verify(self.repo, self.dataset), [])

    def test_duplicate_snapshots_are_flagged(self):
        path, _ = issue(self.repo, self.dataset, self.analysis, "K1", "1", "巡展方丙", "2026-07-01")
        self.reload()
        forged = path.with_name("K1@1-deadbeef0000.json")
        forged.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        problems = verify(self.repo, self.dataset)
        self.assertTrue(any("多份快照" in p for p in problems))

    def test_missing_snapshot_is_flagged(self):
        problems = verify(self.repo, self.dataset)
        self.assertEqual(problems, [])  # 没有已签发展签时无问题
        backfill_snapshots(self.repo, self.dataset)  # 无已签发版本，什么也不写
        # 手工把 K1 登记为已签发但不建快照
        labels_file = self.repo / "fixtures" / "labels.csv"
        text = labels_file.read_text(encoding="utf-8").replace(
            "K1,1,approved,,,", "K1,1,issued,巡展方丙,2026-07-01,"
        )
        labels_file.write_text(text, encoding="utf-8")
        self.reload()
        problems = verify(self.repo, self.dataset)
        self.assertTrue(any("缺快照" in p for p in problems))
        # 补建后通过
        written, _ = backfill_snapshots(self.repo, self.dataset)
        self.assertEqual(len(written), 1)
        self.assertEqual(verify(self.repo, self.dataset), [])


class RepoFixtureVerifyTests(unittest.TestCase):
    def test_committed_snapshots_match_fixtures(self):
        dataset = load_dataset(ROOT / "fixtures")
        self.assertEqual(verify(ROOT, dataset), [])


if __name__ == "__main__":
    unittest.main()
