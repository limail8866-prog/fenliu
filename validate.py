#!/usr/bin/env python3
"""Validate rule syntax, duplicate rules, category overlap and policy references."""

import argparse
import sys
from pathlib import Path

from rulelib import ROOT, SourceError, load_sources


def main() -> int:
    parser = argparse.ArgumentParser(description="校验源规则与策略映射")
    parser.add_argument("--rules-dir", type=Path, default=ROOT / "rules")
    parser.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
    args = parser.parse_args()
    try:
        categories, _ = load_sources(args.rules_dir, args.policy)
    except SourceError as exc:
        print(f"校验失败：\n{exc}", file=sys.stderr)
        return 1
    print(f"校验通过：{len(categories)} 个分类，{sum(map(len, categories.values()))} 条规则")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
