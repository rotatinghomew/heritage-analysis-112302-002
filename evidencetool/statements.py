"""展签语句与整签评估：确定性陈述、多说法、授权与引文。

确定性陈述须在全部仍成立的整图解释里都站得住，且达到馆方证据手册
的最低支持标准；多说法可以并呈，但每种都必须属于某个仍成立的整图
解释（有连续一致的图层范围）。仅供馆内研究的材料不得复制上展签，
引用必须保留许可对象与展示范围。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .analysis import MANUAL_MIN_FAMILIES, Analysis
from .model import Dataset, Label, Statement

CERTAINTY = "certainty"
ALTERNATIVE = "alternative"

#: 展签状态 × 语句是否全部通过 -> 结论
VERDICTS = {
    ("issued", True): "可继续使用",
    ("issued", False): "必须更换",
    ("approved", True): "可签发",
    ("approved", False): "需修改后方可签发",
    ("draft", True): "可送审",
    ("draft", False): "草稿待补",
}


@dataclass
class StatementResult:
    statement: Statement
    ok: bool
    problems: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()  # 补救还缺的证据或授权
    images: tuple[int, ...] = ()  # 所属整图解释编号（从 1 起）


def evaluate_statement(st: Statement, dataset: Dataset, analysis: Analysis) -> StatementResult:
    problems: list[str] = []
    warnings: list[str] = []
    gaps: list[str] = []
    images: tuple[int, ...] = ()

    if st.kind not in (CERTAINTY, ALTERNATIVE):
        problems.append(f"语句种类 {st.kind!r} 未登记（应为 certainty/alternative）")

    interp = dataset.interpretation_by_id().get(st.interpretation)
    if interp is None:
        problems.append(f"解释 {st.interpretation} 未登记")
    else:
        viab = analysis.viability[st.interpretation]
        sup = analysis.support[(interp.object, interp.phase)]
        containing = tuple(i + 1 for i in analysis.images_containing(st.interpretation))
        if st.kind == CERTAINTY:
            if not viab.viable:
                problems.append(f"解释 {st.interpretation} 已不成立：" + "；".join(viab.problems))
                gaps.append(f"为 {interp.object}/{interp.phase} 寻找新的依据")
            elif not analysis.images:
                problems.append("当前没有仍成立的整图解释")
            elif len(containing) < len(analysis.images):
                where = f"仅整图 {list(containing)}" if containing else "不在任何整图中"
                problems.append(
                    f"解释 {st.interpretation} 未出现在全部仍成立的整图解释中（{where}）"
                )
                gaps.append("改为多说法并呈，或等待能排除其他解释的新证据")
            if not sup.meets_manual:
                problems.append(
                    f"独立支持 {sup.count} 家，低于馆方证据手册标准 {MANUAL_MIN_FAMILIES} 家"
                )
                gaps.append(f"补足可追到原件的独立证据（现 {sup.count}/{MANUAL_MIN_FAMILIES} 家）")
            if sup.contradicting:
                ids = "、".join(r.record for r in sup.contradicting)
                problems.append(f"存在适用的反驳证据：{ids}")
        elif st.kind == ALTERNATIVE:
            if not viab.viable:
                problems.append(f"解释 {st.interpretation} 已不成立：" + "；".join(viab.problems))
                gaps.append(f"为 {interp.object}/{interp.phase} 寻找新的依据")
            elif not containing:
                problems.append(f"解释 {st.interpretation} 不在任何仍成立的整图解释中")
            images = containing
        warnings.extend(viab.warnings)

    accesses = dataset.source_access()
    if st.image_source:
        acc = accesses.get(st.image_source)
        if acc is None:
            problems.append(f"图像来源 {st.image_source} 未登记")
        elif "research" in acc:
            problems.append(f"{st.image_source} 仅供馆内研究，原图或限制摘录不得上展签")
            gaps.append(f"取得 {st.image_source} 的展陈授权，或撤下该图像/摘录")
        if not st.licensee or not st.display_scope:
            problems.append("复制材料须保留许可对象与展示范围")
            gaps.append("补记许可对象与展示范围")

    by_id = dataset.evidence_by_id()
    cites_restricted = False
    for cid in st.cites:
        rec = by_id.get(cid)
        if rec is None:
            problems.append(f"引文 {cid} 无对应记录")
        elif rec.access == "research":
            cites_restricted = True
    if cites_restricted and (not st.licensee or not st.display_scope):
        problems.append("引用限制材料须保留许可对象与展示范围")
        gaps.append("补记许可对象与展示范围")

    return StatementResult(
        statement=st,
        ok=not problems,
        problems=tuple(problems),
        warnings=tuple(warnings),
        gaps=tuple(dict.fromkeys(gaps)),
        images=images,
    )


@dataclass
class LabelVerdict:
    label: Label
    results: list[StatementResult] = field(default_factory=list)
    verdict: str = ""
    problems: tuple[str, ...] = ()
    gaps: tuple[str, ...] = ()


def evaluate_label(label: Label, dataset: Dataset, analysis: Analysis) -> LabelVerdict:
    stmts = dataset.statements_for(label.ident, label.version)
    results = [evaluate_statement(s, dataset, analysis) for s in stmts]
    problems: list[str] = []
    gaps: list[str] = []
    if not stmts:
        problems.append("该版本没有任何语句")
    for res in results:
        problems.extend(f"{res.statement.ident}：{p}" for p in res.problems)
        for gap in res.gaps:
            if gap not in gaps:
                gaps.append(gap)
    verdict = VERDICTS.get((label.status, not problems), f"状态 {label.status!r} 未登记")
    return LabelVerdict(label, results, verdict, tuple(problems), tuple(gaps))


def evaluate_labels(dataset: Dataset, analysis: Analysis) -> list[LabelVerdict]:
    return [evaluate_label(label, dataset, analysis) for label in dataset.labels]
