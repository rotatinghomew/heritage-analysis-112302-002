"""签发登记：已签发展签的快照、回查与防冒充校验。

已审签发给巡展方的标签按原内容留存快照（内容寻址），可随时按原内容
回查；旧稿被改正后，新稿只能以新版本签发，不能冒充原巡展方收到的内容。
"""
from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .analysis import Analysis
from .model import Dataset, Label, Statement
from .statements import evaluate_label

ISSUED_DIR = "issued"


def payload_for(label: Label, statements: list[Statement]) -> dict:
    """签发内容的规范表示（哈希与快照都以此为准）。"""
    return {
        "label": label.ident,
        "version": label.version,
        "issued_to": label.issued_to or "",
        "issued_on": label.issued_on or "",
        "statements": [
            {
                "statement": s.ident,
                "group": s.group or "",
                "kind": s.kind,
                "interpretation": s.interpretation,
                "text": s.text,
                "image_source": s.image_source or "",
                "licensee": s.licensee or "",
                "display_scope": s.display_scope or "",
                "cites": list(s.cites),
            }
            for s in sorted(statements, key=lambda x: x.ident)
        ],
    }


def content_hash(payload: dict) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def snapshot_name(label_id: str, version: str, digest: str) -> str:
    return f"{label_id}@{version}-{digest[:12]}.json"


def write_snapshot(repo: Path, label: Label, statements: list[Statement]) -> Path:
    payload = payload_for(label, statements)
    digest = content_hash(payload)
    doc = dict(payload)
    doc["content_hash"] = digest
    issued_dir = repo / ISSUED_DIR
    issued_dir.mkdir(exist_ok=True)
    path = issued_dir / snapshot_name(label.ident, label.version, digest)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _snapshots(repo: Path) -> dict[tuple[str, str], list[Path]]:
    issued_dir = repo / ISSUED_DIR
    found: dict[tuple[str, str], list[Path]] = {}
    if issued_dir.is_dir():
        for path in sorted(issued_dir.glob("*@*-*.json")):
            stem = path.name[: -len(".json")]
            label_ver, _ = stem.rsplit("-", 1)
            label_id, version = label_ver.split("@", 1)
            found.setdefault((label_id, version), []).append(path)
    return found


def verify(repo: Path, dataset: Dataset) -> list[str]:
    """校验已签发内容未被改动。返回问题清单（空表示通过）。"""
    problems: list[str] = []
    snapshots = _snapshots(repo)
    for label in dataset.labels:
        if label.status != "issued":
            continue
        key = (label.ident, label.version)
        files = snapshots.pop(key, [])
        if not files:
            problems.append(f"{label.ident} v{label.version} 已登记签发但缺快照")
            continue
        if len(files) > 1:
            problems.append(f"{label.ident} v{label.version} 存在多份快照，疑似冒充")
        doc = json.loads(files[0].read_text(encoding="utf-8"))
        stored = doc.get("content_hash", "")
        body = {k: v for k, v in doc.items() if k != "content_hash"}
        if content_hash(body) != stored:
            problems.append(f"{label.ident} v{label.version} 快照文件自身校验失败")
        current = content_hash(payload_for(label, dataset.statements_for(label.ident, label.version)))
        if current != stored:
            problems.append(
                f"{label.ident} v{label.version} 当前稿件与签发内容不符，"
                "疑似以新稿冒充巡展方实际收到的内容"
            )
        if doc.get("issued_to", "") != (label.issued_to or "") or doc.get("issued_on", "") != (
            label.issued_on or ""
        ):
            problems.append(f"{label.ident} v{label.version} 签发登记与快照不符")
    for (label_id, version), files in sorted(snapshots.items()):
        problems.append(f"{label_id} v{version} 存在快照但未登记签发（{files[0].name}）")
    return problems


def as_issued(repo: Path, label_id: str, version: str | None = None) -> list[dict]:
    """按原内容回查巡展方实际收到的标签。"""
    snapshots = _snapshots(repo)
    docs: list[dict] = []
    for (lid, ver), files in sorted(snapshots.items()):
        if lid != label_id:
            continue
        if version is not None and ver != version:
            continue
        docs.append(json.loads(files[0].read_text(encoding="utf-8")))
    return docs


def issue(repo: Path, dataset: Dataset, analysis: Analysis, label_id: str, version: str,
          issued_to: str, issued_on: str) -> tuple[Path | None, list[str]]:
    """签发一个展签版本：先评估，通过后更新登记并写快照。

    已签发版本不能重复签发；有未通过问题的版本拒绝签发。
    """
    label = next(
        (lab for lab in dataset.labels if lab.ident == label_id and lab.version == version), None
    )
    if label is None:
        return None, [f"展签 {label_id} 版本 {version} 未登记"]
    if label.status == "issued":
        return None, [f"{label_id} v{version} 已签发，不能改动；如需更正请新建版本"]
    verdict = evaluate_label(label, dataset, analysis)
    if verdict.problems:
        return None, [f"{label_id} v{version} 存在未通过的问题，拒绝签发："] + list(verdict.problems)
    if len(dataset.labels_files) != 1:
        return None, ["展签登记分散在多个文件中，无法自动更新，请合并后再签发"]
    labels_file = dataset.labels_files[0]
    with labels_file.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fields = reader.fieldnames or []
        rows = list(reader)
    for row in rows:
        if row.get("label") == label_id and row.get("version") == version:
            row["status"] = "issued"
            row["issued_to"] = issued_to
            row["issued_on"] = issued_on
    with labels_file.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    updated = Label(label.ident, label.version, "issued", issued_to, issued_on, label.supersedes)
    path = write_snapshot(repo, updated, dataset.statements_for(label_id, version))
    return path, []


def backfill_snapshots(repo: Path, dataset: Dataset) -> tuple[list[Path], list[str]]:
    """为已登记签发但缺快照的版本补建快照；已有快照绝不覆盖。"""
    written: list[Path] = []
    problems: list[str] = []
    snapshots = _snapshots(repo)
    for label in dataset.labels:
        if label.status != "issued":
            continue
        key = (label.ident, label.version)
        if key in snapshots:
            continue
        written.append(write_snapshot(repo, label, dataset.statements_for(label.ident, label.version)))
    return written, problems
