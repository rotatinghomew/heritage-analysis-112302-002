"""展签语句与整签评估测试。"""
from pathlib import Path
import unittest

from evidencetool.analysis import analyze
from evidencetool.loader import load_dataset
from evidencetool.statements import evaluate_labels, evaluate_statement

ROOT = Path(__file__).resolve().parents[1]


class StatementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "fixtures")
        cls.analysis = analyze(cls.dataset)

    def result(self, ident):
        st = next(s for s in self.dataset.statements if s.ident == ident)
        return evaluate_statement(st, self.dataset, self.analysis)

    def test_certainty_statement_passes_when_in_all_sets(self):
        res = self.result("S1")  # I4 在全部整图解释中，独立支持 2 家
        self.assertTrue(res.ok, res.problems)

    def test_certainty_statement_fails_when_not_in_all_sets(self):
        res = self.result("S4")  # I2 只在整图 2 中
        self.assertFalse(res.ok)
        self.assertTrue(any("未出现在全部" in p for p in res.problems))

    def test_research_only_image_cannot_go_on_label(self):
        res = self.result("S4")
        self.assertTrue(any("仅供馆内研究" in p for p in res.problems))
        self.assertTrue(any("展陈授权" in g for g in res.gaps))

    def test_licensee_and_scope_required(self):
        res = self.result("S4")
        self.assertTrue(any("许可对象与展示范围" in p for p in res.problems))

    def test_alternative_statement_points_to_its_image(self):
        res = self.result("S2")
        self.assertTrue(res.ok)
        self.assertEqual(res.images, (1,))

    def test_unknown_citation_is_flagged(self):
        dataset = self.dataset
        st = type(self.dataset.statements[0])(
            label="X", version="1", ident="SX", group=None, kind="alternative",
            interpretation="I1", text="测试", image_source=None,
            licensee=None, display_scope=None, cites=("E99",),
        )
        res = evaluate_statement(st, dataset, self.analysis)
        self.assertTrue(any("E99" in p and "无对应记录" in p for p in res.problems))


class LabelVerdictTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_dataset(ROOT / "fixtures")
        cls.analysis = analyze(cls.dataset)
        cls.verdicts = {
            (v.label.ident, v.label.version): v
            for v in evaluate_labels(cls.dataset, cls.analysis)
        }

    def test_baseline_verdicts(self):
        self.assertEqual(self.verdicts[("L1", "1")].verdict, "可继续使用")
        self.assertEqual(self.verdicts[("L1", "2")].verdict, "可送审")
        self.assertEqual(self.verdicts[("L2", "1")].verdict, "需修改后方可签发")
        self.assertEqual(self.verdicts[("L3", "1")].verdict, "可继续使用")

    def test_after_redating_issued_label_must_be_replaced(self):
        updated, _ = self.dataset.apply_updates()
        analysis = analyze(updated)
        verdicts = {
            (v.label.ident, v.label.version): v
            for v in evaluate_labels(updated, analysis)
        }
        self.assertEqual(verdicts[("L1", "1")].verdict, "必须更换")
        self.assertEqual(verdicts[("L3", "1")].verdict, "可继续使用")
        # 替换稿 L1 v2 仍缺证据
        gaps = "；".join(verdicts[("L1", "2")].gaps)
        self.assertIn("独立证据", gaps)
        self.assertIn("door/late", gaps)

    def test_replacement_gaps_mention_authorization(self):
        gaps = "；".join(self.verdicts[("L2", "1")].gaps)
        self.assertIn("MAP-1", gaps)
        self.assertIn("许可对象与展示范围", gaps)


if __name__ == "__main__":
    unittest.main()
