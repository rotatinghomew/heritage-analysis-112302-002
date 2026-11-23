"""数据模型：证据、解释、展签与相关业务实体。

约定（与 docs/数据说明.md 一致）：
- 空值表示来源没有给值；未知、零和缺报三者不同。
- 不同表中的同一标识用于关联记录，不代表两份独立观察。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class Phase:
    """一个建筑期段的年代范围（起止年，闭区间）。"""

    name: str
    start: int
    end: int

    def contains(self, year: int) -> bool:
        return self.start <= year <= self.end


@dataclass(frozen=True)
class Evidence:
    """一条证据记录（测绘、照片、引文、档案等）。

    year 为 None 表示年代缺报（未知）：缺报记录既不算支持也不算反驳，
    与“记年为零”或“记年落在期段外”不同。
    """

    record: str
    source: str
    parent: str  # 来源家族根（同一原件）
    object: str  # 构件
    phase: str  # 期段
    claim: str  # supports / contradicts
    relation: str  # independent / copy
    year: int | None
    access: str  # research / exhibition
    origin: str = ""  # 来自哪个输入文件，便于回查


@dataclass(frozen=True)
class Interpretation:
    """一个局部解释：某构件在某期段的形态判断。"""

    ident: str
    object: str
    phase: str
    requires: tuple[str, ...]  # 依据的证据记录
    conflicts: tuple[str, ...]  # 声明互斥的其他解释


@dataclass(frozen=True)
class Ordering:
    """建造先后条件：before 解释的建造必须先于 after 解释。"""

    before: str
    after: str


@dataclass(frozen=True)
class Doubt:
    """来源之间存疑的抄录关系。"""

    source_a: str
    source_b: str
    note: str


@dataclass(frozen=True)
class Update:
    """重新断代事件：某来源被改定到新的年份。"""

    source: str
    year: int
    reason: str


@dataclass(frozen=True)
class Statement:
    """展签上的一句陈述。"""

    label: str
    version: str
    ident: str
    group: str | None  # 多说法分组；同组语句互为备选
    kind: str  # certainty / alternative
    interpretation: str  # 所断言的解释
    text: str
    image_source: str | None  # 复制上展签的原图/摘录来源
    licensee: str | None  # 许可对象
    display_scope: str | None  # 展示范围
    cites: tuple[str, ...]  # 引文（证据记录号）


@dataclass(frozen=True)
class Label:
    """展签的一个版本。已签发版本的内容不可改写。"""

    ident: str
    version: str
    status: str  # draft / approved / issued
    issued_to: str | None
    issued_on: str | None
    supersedes: str | None


@dataclass
class Dataset:
    """一次评估所需的全部输入。"""

    evidence: list[Evidence]
    interpretations: list[Interpretation]
    phases: dict[str, Phase]
    dates: dict[str, tuple[int, int]]  # 解释 -> 年代区间
    orderings: list[Ordering]
    doubts: list[Doubt]
    updates: list[Update]
    labels: list[Label]
    statements: list[Statement]
    warnings: list[str]
    fixtures_dir: Path
    labels_files: list[Path]

    def evidence_by_id(self) -> dict[str, Evidence]:
        return {e.record: e for e in self.evidence}

    def interpretation_by_id(self) -> dict[str, Interpretation]:
        return {i.ident: i for i in self.interpretations}

    def source_access(self) -> dict[str, set[str]]:
        """每个来源出现过的授权级别（同一来源可能有多条记录）。"""
        acc: dict[str, set[str]] = {}
        for e in self.evidence:
            acc.setdefault(e.source, set()).add(e.access)
        return acc

    def statements_for(self, label: str, version: str) -> list[Statement]:
        return [s for s in self.statements if s.label == label and s.version == version]

    def apply_updates(self) -> tuple["Dataset", list[tuple[Evidence, Update]]]:
        """应用重新断代，返回新数据集与被改动的记录清单。原数据集不变。"""
        by_source = {u.source: u for u in self.updates}
        changes: list[tuple[Evidence, Update]] = []
        new_evidence: list[Evidence] = []
        for e in self.evidence:
            u = by_source.get(e.source)
            if u is not None and e.year != u.year:
                changes.append((e, u))
                new_evidence.append(replace(e, year=u.year))
            else:
                new_evidence.append(e)
        return replace(self, evidence=new_evidence), changes
