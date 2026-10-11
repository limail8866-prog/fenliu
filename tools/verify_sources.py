#!/usr/bin/env python3
"""Verify the pinned upstream snapshots without modifying source files."""

import hashlib
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rulelib import ROOT, SourceError, load_sources, normalize, read_yaml


def main() -> int:
    manifest = read_yaml(ROOT / "sources.yaml")
    categories, _ = load_sources()
    base = f"https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/{manifest['commit']}"
    try:
        for source in manifest["sources"]:
            with urlopen(f"{base}/{source['path']}", timeout=30) as response:
                raw = response.read()
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise SourceError(f"来源摘要不匹配：{source['path']}")
            upstream = set(raw.decode("utf-8").splitlines())
            local = {(rule.type, rule.value) for rule in categories[source["category"]]}
            for line in source["selected"]:
                rule_type, value, *_ = line.split(",")
                if line not in upstream or (rule_type, normalize(rule_type, value)) not in local:
                    raise SourceError(f"选取规则未同时存在于上游及本地：{line}")
            print(f"来源核验通过：{source['path']}（精选 {len(source['selected'])} 条）")
    except (SourceError, URLError, OSError) as exc:
        print(f"来源核验失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
