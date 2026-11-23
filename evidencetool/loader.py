"""CSV 载入：按表头识别文件角色，同类文件合并。

文件角色不由文件名决定，而由表头包含的字段决定；
无法识别的文件跳过并记入警告。
"""
from __future__ import annotations

import csv
from pathlib import Path

from .model import (
    Dataset,
    Doubt,
    Evidence,
    Interpretation,
    Label,
    Ordering,
    Phase,
    Statement,
    Update,
)

# 角色 -> 必须出现的字段。顺序即匹配优先级。
ROLES: list[tuple[str, frozenset[str]]] = [
    (
        "statements",
        frozenset(
            {
                "label",
                "version",
                "statement",
                "group",
                "kind",
                "interpretation",
                "text",
                "image_source",
                "licensee",
                "display_scope",
                "cites",
            }
        ),
    ),
    (
        "evidence",
        frozenset(
            {
                "record",
                "source",
                "parent",
                "object",
                "phase",
                "claim",
                "relation",
                "year",
                "access",
            }
        ),
    ),
    (
        "labels",
        frozenset({"label", "version", "status", "issued_to", "issued_on", "supersedes"}),
    ),
    (
        "interpretations",
        frozenset({"interpretation", "object", "phase", "requires", "conflicts"}),
    ),
    ("dates", frozenset({"interpretation", "start", "end"})),
    ("phases", frozenset({"phase", "start", "end"})),
    ("ordering", frozenset({"before", "after"})),
    ("doubts", frozenset({"source_a", "source_b", "note"})),
    ("updates", frozenset({"source", "year", "reason"})),
]


def classify(header: list[str]) -> str | None:
    cols = frozenset(h for h in header if h)
    for role, required in ROLES:
        if required <= cols:
            return role
    return None


def _int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _list(text: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in text.split(";") if part.strip())


def _none(text: str) -> str | None:
    text = text.strip()
    return text or None


def load_dataset(fixtures_dir: Path | str) -> Dataset:
    fixtures_dir = Path(fixtures_dir)
    evidence: list[Evidence] = []
    interpretations: list[Interpretation] = []
    phases: dict[str, Phase] = {}
    dates: dict[str, tuple[int, int]] = {}
    orderings: list[Ordering] = []
    doubts: list[Doubt] = []
    updates: list[Update] = []
    labels: list[Label] = []
    statements: list[Statement] = []
    warnings: list[str] = []
    labels_files: list[Path] = []

    for path in sorted(fixtures_dir.glob("*.csv")):
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            header = list(reader.fieldnames or [])
            role = classify(header)
            rows = [
                {k: (v.strip() if isinstance(v, str) else "") for k, v in row.items() if k}
                for row in reader
            ]
        if role is None:
            warnings.append(f"{path.name}：表头未识别，已跳过")
            continue
        for row in rows:
            if role == "evidence":
                year = _int(row.get("year", ""))
                if row.get("year", "") and year is None:
                    warnings.append(f"{path.name}：{row.get('record')} 的年份无法解析，按缺报处理")
                if not row.get("relation", ""):
                    warnings.append(f"{path.name}：{row.get('record')} 缺 relation，按 independent 处理")
                if row.get("relation") == "copy" and row.get("parent") == row.get("source"):
                    warnings.append(f"{path.name}：{row.get('record')} 是复制记录但原件指向自身")
                evidence.append(
                    Evidence(
                        record=row.get("record", ""),
                        source=row.get("source", ""),
                        parent=row.get("parent", "") or row.get("source", ""),
                        object=row.get("object", ""),
                        phase=row.get("phase", ""),
                        claim=row.get("claim", ""),
                        relation=row.get("relation", "") or "independent",
                        year=year,
                        access=row.get("access", "") or "research",
                        origin=path.name,
                    )
                )
            elif role == "interpretations":
                interpretations.append(
                    Interpretation(
                        ident=row.get("interpretation", ""),
                        object=row.get("object", ""),
                        phase=row.get("phase", ""),
                        requires=_list(row.get("requires", "")),
                        conflicts=_list(row.get("conflicts", "")),
                    )
                )
            elif role == "phases":
                start, end = _int(row.get("start", "")), _int(row.get("end", ""))
                if start is None or end is None:
                    warnings.append(f"{path.name}：期段 {row.get('phase')} 缺起止年，已跳过")
                    continue
                phases[row.get("phase", "")] = Phase(row.get("phase", ""), start, end)
            elif role == "dates":
                start, end = _int(row.get("start", "")), _int(row.get("end", ""))
                if start is None or end is None:
                    warnings.append(f"{path.name}：解释 {row.get('interpretation')} 的年代区间不完整，已跳过")
                    continue
                dates[row.get("interpretation", "")] = (start, end)
            elif role == "ordering":
                orderings.append(Ordering(before=row.get("before", ""), after=row.get("after", "")))
            elif role == "doubts":
                doubts.append(
                    Doubt(
                        source_a=row.get("source_a", ""),
                        source_b=row.get("source_b", ""),
                        note=row.get("note", ""),
                    )
                )
            elif role == "updates":
                year = _int(row.get("year", ""))
                if year is None:
                    warnings.append(f"{path.name}：{row.get('source')} 的改定年份缺失或无法解析，已跳过")
                    continue
                updates.append(Update(source=row.get("source", ""), year=year, reason=row.get("reason", "")))
            elif role == "labels":
                if path not in labels_files:
                    labels_files.append(path)
                labels.append(
                    Label(
                        ident=row.get("label", ""),
                        version=row.get("version", ""),
                        status=row.get("status", "") or "draft",
                        issued_to=_none(row.get("issued_to", "")),
                        issued_on=_none(row.get("issued_on", "")),
                        supersedes=_none(row.get("supersedes", "")),
                    )
                )
            elif role == "statements":
                statements.append(
                    Statement(
                        label=row.get("label", ""),
                        version=row.get("version", ""),
                        ident=row.get("statement", ""),
                        group=_none(row.get("group", "")),
                        kind=row.get("kind", ""),
                        interpretation=row.get("interpretation", ""),
                        text=row.get("text", ""),
                        image_source=_none(row.get("image_source", "")),
                        licensee=_none(row.get("licensee", "")),
                        display_scope=_none(row.get("display_scope", "")),
                        cites=_list(row.get("cites", "")),
                    )
                )

    seen_records: set[str] = set()
    for e in evidence:
        if e.record in seen_records:
            warnings.append(f"证据记录号 {e.record} 重复出现")
        seen_records.add(e.record)
        if e.phase and e.phase not in phases and phases:
            warnings.append(f"证据 {e.record} 的期段 {e.phase} 未在期段表中登记")
    seen_labels: set[tuple[str, str]] = set()
    for lab in labels:
        key = (lab.ident, lab.version)
        if key in seen_labels:
            warnings.append(f"展签 {lab.ident} 版本 {lab.version} 重复登记")
        seen_labels.add(key)

    return Dataset(
        evidence=evidence,
        interpretations=interpretations,
        phases=phases,
        dates=dates,
        orderings=orderings,
        doubts=doubts,
        updates=updates,
        labels=labels,
        statements=statements,
        warnings=warnings,
        fixtures_dir=fixtures_dir,
        labels_files=labels_files,
    )
