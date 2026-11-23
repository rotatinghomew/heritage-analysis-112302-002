"""评估结果的文字报告。"""
from __future__ import annotations

from .analysis import MANUAL_MIN_FAMILIES, Analysis, pairwise_relations
from .model import Dataset
from .statements import LabelVerdict


def _families_text(dataset: Dataset, analysis: Analysis) -> list[str]:
    lines = ["来源家族（同一原件的复制记录只计一次独立支持）"]
    by_root: dict[str, list] = {}
    for rec in dataset.evidence:
        by_root.setdefault(rec.parent, []).append(rec)
    for root in sorted(by_root):
        recs = by_root[root]
        marks = "、".join(f"{r.record}({'独立' if r.relation == 'independent' else '复制'})" for r in recs)
        scopes = "、".join(sorted({f"{r.object}/{r.phase}" for r in recs}))
        lines.append(f"  {root}：{marks}　范围 {scopes}")
    return lines


def render_summary(dataset: Dataset, analysis: Analysis) -> str:
    lines = ["== 总览 =="]
    lines.extend(dataset.warnings and [f"⚠ 输入警告：{w}" for w in dataset.warnings] or [])
    viable = sum(1 for v in analysis.viability.values() if v.viable)
    lines.append(
        f"证据 {len(dataset.evidence)} 条；解释 {len(dataset.interpretations)} 个"
        f"（成立 {viable}，不成立 {len(dataset.interpretations) - viable}）；"
        f"仍成立的整图解释 {len(analysis.images)} 组"
    )
    if dataset.updates:
        lines.append(f"待评估的重新断代 {len(dataset.updates)} 项（见 impact）")
    return "\n".join(lines)


def render_families(dataset: Dataset, analysis: Analysis) -> str:
    lines = ["== 来源家族与依赖风险 =="]
    lines.extend(_families_text(dataset, analysis))
    lines.append("")
    lines.append("依赖风险（抄录关系存疑，若成立则家族合并）")
    if not analysis.risks:
        lines.append("  （无）")
    for risk in analysis.risks:
        doubt = risk.doubt
        lines.append(f"  {doubt.source_a} ↔ {doubt.source_b}：{doubt.note}")
        if risk.drops:
            for drop in risk.drops:
                lines.append(f"    ⚠ 若关系成立：{drop}")
        else:
            lines.append("    若关系成立：独立支持计数不变")
    return "\n".join(lines)


def render_relations(dataset: Dataset) -> str:
    lines = ["== 解释两两关系 =="]
    for rel in pairwise_relations(dataset):
        lines.append(f"  {rel.a} ↔ {rel.b}：{'；'.join(rel.kinds)}")
    return "\n".join(lines)


def _layer_basis(dataset: Dataset, analysis: Analysis, ident: str) -> str:
    interp = dataset.interpretation_by_id()[ident]
    sup = analysis.support[(interp.object, interp.phase)]
    fams = "、".join(sorted(sup.families)) or "无"
    basis = f"{interp.object}/{interp.phase} {ident}：独立支持 {sup.count} 家（{fams}）；依据 {'、'.join(interp.requires) or '无'}"
    if sup.contradicting:
        ids = "、".join(r.record for r in sup.contradicting)
        basis += f"；⚠ 反驳证据 {ids}"
    return basis


def render_sets(dataset: Dataset, analysis: Analysis) -> str:
    lines = [f"== 仍成立的整图解释（{len(analysis.images)} 组）=="]
    if not analysis.images:
        lines.append("  （无）")
    for idx, img in enumerate(analysis.images, 1):
        head = f"  整图 {idx}：{' + '.join(img.members)}"
        if img.simultaneous is True:
            head += "　✓ 各层可同时成图"
        elif img.simultaneous is False:
            head += "　⚠ 从未同时出现，不能合成单张确定性复原图"
        else:
            head += "　⚠ 有图层年代缺报，同时性无法判断"
        lines.append(head)
        for note in img.date_conflicts:
            lines.append(f"    ⚠ {note}")
        lines.append("    图层依据：")
        for member in img.members:
            lines.append(f"      {_layer_basis(dataset, analysis, member)}")
    if analysis.gaps:
        lines.append(f"  图层缺口：{'、'.join(analysis.gaps)} 没有仍成立的解释")
    if analysis.strongest:
        picks = "、".join(
            f"{obj}→{'/'.join(ids)}（{count} 家）"
            for obj, (ids, count) in analysis.strongest.items()
        )
        lines.append(f"按构件单独取证据最强的解释：{picks}")
        combo = tuple(
            ids[0] for _obj, (ids, _count) in sorted(analysis.strongest.items()) if len(ids) == 1
        )
        if len(combo) == len(analysis.strongest):
            match = next((img for img in analysis.images if set(img.members) == set(combo)), None)
            if match is not None and match.simultaneous is False:
                lines.append("  ⚠ 该组合从未同时出现：整图的完整不等于每个局部已证实")
                for note in match.date_conflicts:
                    lines.append(f"    ⚠ {note}")
            elif match is None:
                lines.append("  ⚠ 该组合彼此冲突，根本拼不成一张仍成立的整图")
    return "\n".join(lines)


def render_labels(verdicts: list[LabelVerdict], dataset: Dataset, analysis: Analysis) -> str:
    lines = ["== 展签评估 =="]
    for verdict in verdicts:
        label = verdict.label
        head = f"{label.ident} v{label.version}（{label.status}"
        if label.status == "issued":
            head += f"，已发 {label.issued_to} {label.issued_on}"
        if label.supersedes:
            head += f"，接替 v{label.supersedes}"
        head += f"）：{verdict.verdict}"
        lines.append(head)
        for res in verdict.results:
            st = res.statement
            kind = "确定性陈述" if st.kind == "certainty" else "多说法"
            mark = "✓" if res.ok else "✗"
            tail = f"（见整图 {list(res.images)}）" if res.images else ""
            lines.append(f"  {mark} {st.ident} [{kind}→{st.interpretation}] {st.text}{tail}")
            for problem in res.problems:
                lines.append(f"      ✗ {problem}")
            for warning in res.warnings:
                lines.append(f"      ⚠ {warning}")
        if verdict.gaps:
            lines.append(f"  尚缺：{'；'.join(verdict.gaps)}")
    return "\n".join(lines)


def render_impact(dataset: Dataset, analysis: Analysis,
                  updated: Dataset, updated_analysis: Analysis,
                  changes: list, verdicts_now: list[LabelVerdict],
                  verdicts_after: list[LabelVerdict]) -> str:
    lines = ["== 重新断代的影响分析 =="]
    by_update: dict[int, list] = {}
    for rec, upd in changes:
        by_update.setdefault(id(upd), []).append(rec)
    seen: set[int] = set()
    for rec, upd in changes:
        if id(upd) in seen:
            continue
        seen.add(id(upd))
        records = "、".join(r.record for r in by_update[id(upd)])
        lines.append(f"  {upd.source} → {upd.year}（{upd.reason}）：影响记录 {records}")
    before = {i for i, v in analysis.viability.items() if v.viable}
    after = {i for i, v in updated_analysis.viability.items() if v.viable}
    lost = sorted(before - after)
    gained = sorted(after - before)
    if lost:
        lines.append("新失效的解释：")
        for ident in lost:
            reasons = "；".join(updated_analysis.viability[ident].problems)
            lines.append(f"  ✗ {ident}：{reasons}")
    if gained:
        lines.append(f"新成立的解释：{'、'.join(gained)}")
    lines.append(f"整图解释：{len(analysis.images)} 组 → {len(updated_analysis.images)} 组")
    if updated_analysis.gaps:
        lines.append(f"  图层缺口：{'、'.join(updated_analysis.gaps)} 没有仍成立的解释")
    lines.append("")
    lines.append("展签结论（按新证据重新评估）")
    now_by_key = {(v.label.ident, v.label.version): v for v in verdicts_now}
    for verdict in verdicts_after:
        key = (verdict.label.ident, verdict.label.version)
        before_verdict = now_by_key.get(key)
        changed = before_verdict is not None and before_verdict.verdict != verdict.verdict
        marker = "【变化】" if changed else ""
        label = verdict.label
        head = f"  {label.ident} v{label.version}（{label.status}"
        if label.status == "issued":
            head += f"，已发 {label.issued_to}"
        head += f"）：{verdict.verdict}{marker}"
        lines.append(head)
        for problem in verdict.problems:
            lines.append(f"    ✗ {problem}")
        if verdict.gaps:
            lines.append(f"    尚缺：{'；'.join(verdict.gaps)}")
    return "\n".join(lines)
