#!/usr/bin/env python3
"""Move upstream pins to the latest default-branch commits for review."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import yaml

ROOT = Path(__file__).resolve().parents[1]


def latest_commit(repository: str) -> str:
    request = Request(
        f"https://api.github.com/repos/{repository}/commits?per_page=1",
        headers={"Accept": "application/vnd.github+json", "User-Agent": "fenliu-upstream-sync"},
    )
    with urlopen(request, timeout=30) as response:
        commits = json.load(response)
    if not isinstance(commits, list) or not commits:
        raise ValueError(f"GitHub 没有返回上游提交：{repository}")
    sha = commits[0].get("sha")
    if not isinstance(sha, str) or not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError(f"上游提交 SHA 格式非法：{repository}")
    return sha


def bump(path: Path = ROOT / "upstream.yaml") -> dict[str, tuple[str, str]]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    changed = {}
    for name, repository in document["repositories"].items():
        old = repository["commit"]
        new = latest_commit(repository["repository"])
        if new != old:
            repository["commit"] = new
            changed[name] = (old, new)
    if changed:
        path.write_text(yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    return changed


def main() -> int:
    try:
        changes = bump()
        if changes:
            for name, (old, new) in changes.items():
                print(f"{name}: {old[:12]} -> {new[:12]}")
        else:
            print("上游提交没有变化")
    except (OSError, KeyError, TypeError, ValueError) as exc:
        print(f"更新上游版本失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
