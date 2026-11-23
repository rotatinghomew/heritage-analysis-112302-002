"""核心评估逻辑测试：来源家族、解释成立性、整图解释组合、依赖风险。"""
from pathlib import Path
import unittest

from evidencetool.analysis import (
    MANUAL_MIN_FAMILIES,
    analyze,
    assess_viability,
    dependency_risks,
    doubt_union_find,
    pairwise_relations,
    scope_support,
)
from evidencetool.loader import load_dataset
from evidencetool.model import (
    Dataset,
    Evidence,
    Interpretation,
    Ordering,
    Phase,
)

ROOT = Path(__file__).resolve().parents[1]


def load_repo():
    return load_dataset(ROOT / "fixtures")


class FamilyTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_repo()

    def test_copy_records_do_not_add_independent_support(self):
        # E1 与 E2 同属 MAP-1 家族，roof/early 的独立支持是 MAP-1 与 FIELD-9 两家
        sup = scope_support(self.dataset, "roof", "early")
        self.assertEqual(sup.count, 2)
        self.assertEqual({r.record for r in sup.families["MAP-1"]}, {"E1", "E2"})

    def test_support_counts_per_scope(self):
        self.assertEqual(scope_support(self.dataset, "roof", "late").count, 3)
        self.assertEqual(scope_support(self.dataset, "door", "late").count, 2)
        self.assertEqual(scope_support(self.dataset, "beam", "early").count, 2)
        self.assertEqual(scope_support(self.dataset, "beam", "late").count, 0)

    def test_contradicting_record_is_collected(self):
        sup = scope_support(self.dataset, "beam", "late")
        self.assertEqual([r.record for r in sup.contradicting], ["E3"])

    def test_dependency_doubt_merges_families(self):
        risks = dependency_risks(self.dataset)
        self.assertEqual(len(risks), 1)
        drops = "；".join(risks[0].drops)
        self.assertIn("door/late 独立支持 2→1", drops)
        self.assertIn("低于手册标准", drops)
        self.assertIn("roof/late 独立支持 3→2", drops)
        # roof/late 合并后仍有 2 家，不达“低于手册标准”
        self.assertNotIn("roof/late 独立支持 3→2，低于手册标准", drops)


class ViabilityTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_repo()
        self.interps = self.dataset.interpretation_by_id()

    def test_self_contradicting_basis_is_not_viable(self):
        viab = assess_viability(self.interps["I3"], self.dataset)
        self.assertFalse(viab.viable)
        self.assertTrue(any("反驳" in p for p in viab.problems))

    def test_out_of_scope_required_record_warns(self):
        viab = assess_viability(self.interps["I2"], self.dataset)
        self.assertTrue(viab.viable)
        self.assertTrue(any("E3" in w and "不一致" in w for w in viab.warnings))

    def test_missing_year_is_a_warning_not_a_failure(self):
        dataset = Dataset(
            evidence=[
                Evidence("X1", "SRC", "SRC", "roof", "early", "supports",
                         "independent", None, "research")
            ],
            interpretations=[Interpretation("J1", "roof", "early", ("X1",), ())],
            phases={"early": Phase("early", 1600, 1699)},
            dates={}, orderings=[], doubts=[], updates=[], labels=[],
            statements=[], warnings=[], fixtures_dir=ROOT, labels_files=[],
        )
        viab = assess_viability(dataset.interpretation_by_id()["J1"], dataset)
        self.assertTrue(any("缺报" in w for w in viab.warnings))
        # 缺报记录不计入支持
        self.assertEqual(scope_support(dataset, "roof", "early").count, 0)
        self.assertEqual(len(scope_support(dataset, "roof", "early").unknown_year), 1)


class WholeImageTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_repo()
        self.analysis = analyze(self.dataset)

    def test_maximal_sets(self):
        members = {img.members for img in self.analysis.images}
        self.assertEqual(members, {("I1", "I4", "I5"), ("I2", "I4", "I5")})

    def test_never_simultaneous_flag(self):
        for img in self.analysis.images:
            self.assertFalse(img.simultaneous)
            self.assertTrue(img.date_conflicts)

    def test_strongest_per_object_combo_warns(self):
        self.assertEqual(self.analysis.strongest["roof"], (("I2",), 3))
        combo = {ids[0] for ids, _ in self.analysis.strongest.values()}
        match = next(img for img in self.analysis.images if set(img.members) == combo)
        self.assertFalse(match.simultaneous)

    def test_ordering_cycle_breaks_set(self):
        dataset = Dataset(
            evidence=[
                Evidence("A1", "SA", "SA", "roof", "early", "supports",
                         "independent", 1650, "research"),
                Evidence("B1", "SB", "SB", "beam", "late", "supports",
                         "independent", 1720, "research"),
            ],
            interpretations=[
                Interpretation("JA", "roof", "early", ("A1",), ()),
                Interpretation("JB", "beam", "late", ("B1",), ()),
            ],
            phases={"early": Phase("early", 1600, 1699), "late": Phase("late", 1700, 1799)},
            dates={},
            orderings=[Ordering("JA", "JB"), Ordering("JB", "JA")],
            doubts=[], updates=[], labels=[], statements=[], warnings=[],
            fixtures_dir=ROOT, labels_files=[],
        )
        analysis = analyze(dataset)
        # 先后条件成环：两个解释不能同组，只剩各自的单解释整图
        members = {img.members for img in analysis.images}
        self.assertEqual(members, {("JA",), ("JB",)})

    def test_relations_report(self):
        relations = {(r.a, r.b): r.kinds for r in pairwise_relations(self.dataset)}
        self.assertTrue(any("声明互斥" in k for k in relations[("I1", "I2")]))
        self.assertTrue(any("日期不相交" in k for k in relations[("I1", "I4")]))
        self.assertTrue(any("可共存" == k for k in relations[("I2", "I4")]))


class UpdateTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_repo()
        self.updated, self.changes = self.dataset.apply_updates()
        self.analysis = analyze(self.updated)

    def test_redating_invalidates_interpretations(self):
        self.assertEqual({r.record for r, _ in self.changes}, {"E4", "E5"})
        self.assertFalse(self.analysis.viability["I2"].viable)
        self.assertFalse(self.analysis.viability["I4"].viable)
        self.assertTrue(self.analysis.viability["I1"].viable)

    def test_redated_records_become_inapplicable(self):
        sup = scope_support(self.updated, "roof", "late")
        self.assertEqual(sup.count, 2)  # E4 不再适用，余 SURV-3 与 ARCH-5
        self.assertEqual([r.record for r in sup.inapplicable], ["E4"])

    def test_sets_after_update(self):
        members = {img.members for img in self.analysis.images}
        self.assertEqual(members, {("I1", "I5")})
        self.assertEqual(self.analysis.gaps, ("door",))
        self.assertTrue(self.analysis.images[0].simultaneous)

    def test_manual_minimum_is_two(self):
        self.assertEqual(MANUAL_MIN_FAMILIES, 2)


if __name__ == "__main__":
    unittest.main()
