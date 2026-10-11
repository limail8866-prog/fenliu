#!/usr/bin/env python3
"""Verify the pinned upstream snapshots without modifying source files."""

import hashlib
import sys
from pathlib import Path
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rulelib import ROOT, SourceError, load_sources, normalize, read_yaml
from tools.sync_rules import fetch_snapshot, parse_line


def main() -> int:
    manifest = read_yaml(ROOT / "sources.yaml")
    categories, _ = load_sources()
    snapshots = {}
    try:
        for source in manifest["sources"]:
            repo = manifest["repositories"][source["repository"]]
            identity = (source["repository"], source["path"])
            if identity not in snapshots:
                snapshots[identity] = fetch_snapshot(repo, source["path"], None, False)
            raw = snapshots[identity]
            if hashlib.sha256(raw).hexdigest() != source["sha256"]:
                raise SourceError(f"来源摘要不匹配：{source['path']}")
            upstream = set(raw.decode("utf-8").splitlines())
            local = {(rule.type, rule.value) for rule in categories[source["category"]]}
            for line in source["selected"]:
                parsed = parse_line(line, repo["format"])
                if line not in upstream or parsed not in local:
                    raise SourceError(f"选取规则未同时存在于上游及本地：{line}")
            print(f"来源核验通过：{repo['repository']}/{source['path']}（导入 {len(source['selected'])} 条）")
    except (SourceError, URLError, OSError) as exc:
        print(f"来源核验失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
