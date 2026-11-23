"""命令行入口：python3 -m evidencetool [--repo 目录] <命令>。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import registry, report
from .analysis import analyze
from .loader import load_dataset
from .statements import evaluate_labels


def _load(repo: Path):
    dataset = load_dataset(repo / "fixtures")
    return dataset, analyze(dataset)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evidencetool",
        description="古建复原图的证据冲突与展签授权评估工具",
    )
    parser.add_argument("--repo", default=".", help="仓库根目录（含 fixtures/ 与 issued/）")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("summary", "families", "relations", "sets", "labels", "impact", "verify", "snapshot"):
        sub.add_parser(name)
    p_issue = sub.add_parser("issue", help="评估通过后签发一个展签版本")
    p_issue.add_argument("label")
    p_issue.add_argument("version")
    p_issue.add_argument("--to", required=True, help="巡展方")
    p_issue.add_argument("--on", required=True, help="签发日期 YYYY-MM-DD")
    p_as = sub.add_parser("as-issued", help="按原内容回查巡展方实际收到的标签")
    p_as.add_argument("label")
    p_as.add_argument("version", nargs="?")
    args = parser.parse_args(argv)

    repo = Path(args.repo)
    dataset, analysis = _load(repo)

    if args.cmd == "summary":
        print(report.render_summary(dataset, analysis))
        return 0
    if args.cmd == "families":
        print(report.render_families(dataset, analysis))
        return 0
    if args.cmd == "relations":
        print(report.render_relations(dataset))
        return 0
    if args.cmd == "sets":
        print(report.render_sets(dataset, analysis))
        return 0
    if args.cmd == "labels":
        print(report.render_labels(evaluate_labels(dataset, analysis), dataset, analysis))
        return 0
    if args.cmd == "impact":
        updated, changes = dataset.apply_updates()
        updated_analysis = analyze(updated)
        print(
            report.render_impact(
                dataset,
                analysis,
                updated,
                updated_analysis,
                changes,
                evaluate_labels(dataset, analysis),
                evaluate_labels(updated, updated_analysis),
            )
        )
        return 0
    if args.cmd == "verify":
        problems = registry.verify(repo, dataset)
        if problems:
            print("签发校验未通过：")
            for problem in problems:
                print(f"  ✗ {problem}")
            return 1
        print("签发校验通过：所有已签发快照与登记内容一致")
        return 0
    if args.cmd == "snapshot":
        written, _ = registry.backfill_snapshots(repo, dataset)
        for path in written:
            print(f"已补建快照 {path}")
        if not written:
            print("所有已签发展签均已有快照")
        return 0
    if args.cmd == "issue":
        path, problems = registry.issue(
            repo, dataset, analysis, args.label, args.version, args.to, args.on
        )
        if problems:
            for problem in problems:
                print(f"✗ {problem}")
            return 1
        print(f"已签发并留存快照：{path}")
        return 0
    if args.cmd == "as-issued":
        docs = registry.as_issued(repo, args.label, args.version)
        if not docs:
            print(f"未找到 {args.label} 的签发快照")
            return 1
        for doc in docs:
            print("以下为巡展方实际收到的内容（快照原样，不得以后续稿件冒充）：")
            print(json.dumps(doc, ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
