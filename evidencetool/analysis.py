"""证据评估核心：来源家族、解释成立性、整图解释组合。

对应馆方证据手册（docs/业务规程.md）：
- 只有互相独立且可追到原始记录的两项证据，才构成确定性陈述的最低支持；
- 复制记录沿同一原件形成一个来源家族，不按引用次数累加；
- 日期区间不重叠或建造先后条件冲突的解释不能合在一张确定性复原图中。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations, product

from .model import Dataset, Doubt, Evidence, Interpretation

#: 馆方证据手册：确定性陈述所需的最低独立来源家族数
MANUAL_MIN_FAMILIES = 2


class UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self._parent.setdefault(item, item)
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def doubt_union_find(evidence: list[Evidence], doubts: list[Doubt]) -> UnionFind:
    """把存疑抄录关系涉及的来源家族并起来（用于依赖风险的假设分析）。"""
    uf = UnionFind()
    roots_by_source: dict[str, set[str]] = {}
    for rec in evidence:
        roots_by_source.setdefault(rec.source, set()).add(rec.parent)
    for doubt in doubts:
        roots = roots_by_source.get(doubt.source_a, set()) | roots_by_source.get(doubt.source_b, set())
        roots_list = sorted(roots)
        for other in roots_list[1:]:
            uf.union(roots_list[0], other)
    return uf


@dataclass
class ScopeSupport:
    """某构件/期段范围内的证据适用性与独立支持。"""

    object: str
    phase: str
    families: dict[str, list[Evidence]] = field(default_factory=dict)  # 适用的支持，按家族
    contradicting: list[Evidence] = field(default_factory=list)  # 适用的反驳
    inapplicable: list[Evidence] = field(default_factory=list)  # 记年落在期段外
    unknown_year: list[Evidence] = field(default_factory=list)  # 年代缺报

    @property
    def count(self) -> int:
        return len(self.families)

    @property
    def meets_manual(self) -> bool:
        return self.count >= MANUAL_MIN_FAMILIES


def scope_support(
    dataset: Dataset, obj: str, phase: str, uf: UnionFind | None = None
) -> ScopeSupport:
    """统计某构件/期段的独立支持。

    同一原件（parent 相同）的复制记录只算一个家族；年代缺报的记录
    既不算支持也不算反驳；记年落在期段外的记录不适用。
    """
    result = ScopeSupport(obj, phase)
    for rec in dataset.evidence:
        if rec.object != obj or rec.phase != phase:
            continue
        if rec.year is None:
            result.unknown_year.append(rec)
            continue
        ph = dataset.phases.get(rec.phase)
        if ph is None or not ph.contains(rec.year):
            result.inapplicable.append(rec)
            continue
        if rec.claim == "supports":
            root = uf.find(rec.parent) if uf is not None else rec.parent
            result.families.setdefault(root, []).append(rec)
        elif rec.claim == "contradicts":
            result.contradicting.append(rec)
    return result


@dataclass
class Viability:
    interpretation: str
    viable: bool
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def assess_viability(interp: Interpretation, dataset: Dataset) -> Viability:
    """判断一个解释是否仍成立。

    依据记录必须存在、适用（记年落在期段内），且不得反驳本解释；
    依据中至少要有一条适用的支持记录。年代缺报只产生提示。
    """
    by_id = dataset.evidence_by_id()
    problems: list[str] = []
    warnings: list[str] = []
    supports = 0
    for rid in interp.requires:
        rec = by_id.get(rid)
        if rec is None:
            problems.append(f"依据 {rid} 没有对应记录")
            continue
        ph = dataset.phases.get(rec.phase)
        if rec.year is None:
            warnings.append(f"依据 {rid} 年代缺报，适用性未知")
            applicable = None
        elif ph is None:
            warnings.append(f"依据 {rid} 的期段 {rec.phase} 未登记")
            applicable = None
        elif not ph.contains(rec.year):
            problems.append(
                f"依据 {rid} 失效：{rec.source} 记年为 {rec.year}，"
                f"不在 {rec.phase} 范围 {ph.start}–{ph.end}"
            )
            continue
        else:
            applicable = True
        same_scope = rec.object == interp.object and rec.phase == interp.phase
        if rec.claim == "contradicts" and same_scope:
            problems.append(f"依据 {rid} 实为对本解释的反驳（{rec.source}）")
        elif not same_scope:
            warnings.append(
                f"依据 {rid} 的记录范围为 {rec.object}/{rec.phase}，"
                f"与本解释 {interp.object}/{interp.phase} 不一致"
            )
        elif rec.claim == "supports" and applicable is True:
            supports += 1
    if not interp.requires:
        problems.append("未登记任何依据记录")
    elif supports == 0 and not any("没有对应记录" in p for p in problems):
        problems.append("依据中没有适用的支持记录")
    repo_wide = scope_support(dataset, interp.object, interp.phase)
    if repo_wide.contradicting:
        ids = "、".join(r.record for r in repo_wide.contradicting)
        warnings.append(f"存在适用的反驳证据：{ids}")
    return Viability(interp.ident, not problems, tuple(problems), tuple(warnings))


@dataclass
class WholeImage:
    """一组仍成立的整图解释：每个构件至多取一个解释，彼此不冲突。"""

    members: tuple[str, ...]
    simultaneous: bool | None  # 各层年代区间是否两两相交；None 表示无法判断
    date_conflicts: tuple[str, ...] = ()


def date_range_of(interp: Interpretation, dataset: Dataset) -> tuple[int, int] | None:
    if interp.ident in dataset.dates:
        return dataset.dates[interp.ident]
    ph = dataset.phases.get(interp.phase)
    return (ph.start, ph.end) if ph else None


def _has_cycle(ids: set[str], orderings) -> bool:
    """成员之间的建造先后条件是否成环（含两两矛盾）。"""
    edges = [(o.before, o.after) for o in orderings if o.before in ids and o.after in ids]
    indeg = {i: 0 for i in ids}
    adj = {i: [] for i in ids}
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1
    stack = [i for i in ids if indeg[i] == 0]
    seen = 0
    while stack:
        node = stack.pop()
        seen += 1
        for nxt in adj[node]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                stack.append(nxt)
    return seen != len(ids)


def maximal_sets(dataset: Dataset, viability: dict[str, Viability]) -> tuple[list[WholeImage], tuple[str, ...]]:
    """枚举仍成立的整图解释（按包含关系取极大集）。

    同一构件的多个解释互为备选；声明互斥与建造先后成环的组合排除。
    返回（整图列表, 无成立解释的构件）。
    """
    interps = dataset.interpretation_by_id()
    viable_ids = [i.ident for i in dataset.interpretations if viability[i.ident].viable]
    by_object: dict[str, list[str]] = {}
    for iid in viable_ids:
        by_object.setdefault(interps[iid].object, []).append(iid)
    objects = sorted({i.object for i in dataset.interpretations})
    gaps = tuple(o for o in objects if o not in by_object)

    declared = set()
    for i in dataset.interpretations:
        for other in i.conflicts:
            declared.add(frozenset((i.ident, other)))

    combos: list[tuple[str, ...]] = []
    choices = [by_object.get(o, []) + [None] for o in objects]
    for combo in product(*choices):
        members = tuple(sorted(m for m in combo if m))
        if not members:
            continue
        ids = set(members)
        if any(frozenset(pair) in declared for pair in combinations(ids, 2)):
            continue
        if _has_cycle(ids, dataset.orderings):
            continue
        combos.append(members)
    maximal = [c for c in combos if not any(set(c) < set(other) for other in combos)]

    images: list[WholeImage] = []
    for members in sorted(maximal):
        ranges = {m: date_range_of(interps[m], dataset) for m in members}
        simultaneous: bool | None = True
        unknown = False
        conflicts_out: list[str] = []
        for a, b in combinations(members, 2):
            ra, rb = ranges[a], ranges[b]
            if ra is None or rb is None:
                unknown = True
            elif ra[1] < rb[0] or rb[1] < ra[0]:
                simultaneous = False
                conflicts_out.append(f"{a} {ra[0]}–{ra[1]} 与 {b} {rb[0]}–{rb[1]} 不相交")
        if simultaneous and unknown:
            simultaneous = None
        images.append(WholeImage(members, simultaneous, tuple(conflicts_out)))
    return images, gaps


@dataclass
class Relation:
    a: str
    b: str
    kinds: tuple[str, ...]


def pairwise_relations(dataset: Dataset) -> list[Relation]:
    """解释两两之间的关系：同层备选、声明互斥、建造先后、日期不相交。"""
    interps = dataset.interpretation_by_id()
    relations: list[Relation] = []
    for a, b in combinations(sorted(interps), 2):
        ia, ib = interps[a], interps[b]
        kinds: list[str] = []
        if ia.object == ib.object:
            kinds.append(f"同层备选（{ia.object}）")
        if b in ia.conflicts or a in ib.conflicts:
            kinds.append("声明互斥")
        for o in dataset.orderings:
            if {o.before, o.after} == {a, b}:
                kinds.append(f"建造先后：{o.before} 先于 {o.after}")
        ra, rb = date_range_of(ia, dataset), date_range_of(ib, dataset)
        if ra and rb and (ra[1] < rb[0] or rb[1] < ra[0]):
            kinds.append(f"日期不相交（{ra[0]}–{ra[1]} / {rb[0]}–{rb[1]}）")
        if not kinds:
            kinds.append("可共存")
        relations.append(Relation(a, b, tuple(kinds)))
    return relations


@dataclass
class DoubtRisk:
    doubt: Doubt
    drops: tuple[str, ...]  # 若抄录关系成立，哪些范围的独立支持会下降


def dependency_risks(dataset: Dataset) -> list[DoubtRisk]:
    """逐条评估存疑抄录关系：若成立，独立支持会如何缩水。"""
    risks: list[DoubtRisk] = []
    for doubt in dataset.doubts:
        uf = doubt_union_find(dataset.evidence, [doubt])
        scopes = {
            (e.object, e.phase)
            for e in dataset.evidence
            if e.source in (doubt.source_a, doubt.source_b)
        }
        drops: list[str] = []
        for obj, phase in sorted(scopes):
            base = scope_support(dataset, obj, phase).count
            merged = scope_support(dataset, obj, phase, uf=uf).count
            if merged < base:
                mark = "，低于手册标准" if merged < MANUAL_MIN_FAMILIES else ""
                drops.append(f"{obj}/{phase} 独立支持 {base}→{merged}{mark}")
        risks.append(DoubtRisk(doubt, tuple(drops)))
    return risks


@dataclass
class Analysis:
    """一次完整评估的结果。"""

    dataset: Dataset
    viability: dict[str, Viability]
    support: dict[tuple[str, str], ScopeSupport]
    images: list[WholeImage]
    gaps: tuple[str, ...]
    strongest: dict[str, tuple[tuple[str, ...], int]]  # 构件 -> (并列最强的解释, 家族数)
    risks: list[DoubtRisk]

    def images_containing(self, interpretation: str) -> list[int]:
        return [i for i, img in enumerate(self.images) if interpretation in img.members]


def analyze(dataset: Dataset) -> Analysis:
    viability = {i.ident: assess_viability(i, dataset) for i in dataset.interpretations}
    scopes = {(i.object, i.phase) for i in dataset.interpretations} | {
        (e.object, e.phase) for e in dataset.evidence
    }
    support = {s: scope_support(dataset, s[0], s[1]) for s in sorted(scopes)}
    images, gaps = maximal_sets(dataset, viability)

    strongest: dict[str, tuple[tuple[str, ...], int]] = {}
    interps = dataset.interpretation_by_id()
    viable_by_object: dict[str, list[str]] = {}
    for i in dataset.interpretations:
        if viability[i.ident].viable:
            viable_by_object.setdefault(i.object, []).append(i.ident)
    for obj, ids in sorted(viable_by_object.items()):
        scored = sorted(
            ((support[(interps[i].object, interps[i].phase)].count, i) for i in ids),
            reverse=True,
        )
        best = scored[0][0]
        tied = tuple(sorted(i for count, i in scored if count == best))
        strongest[obj] = (tied, best)

    return Analysis(
        dataset=dataset,
        viability=viability,
        support=support,
        images=images,
        gaps=gaps,
        strongest=strongest,
        risks=dependency_risks(dataset),
    )
