#!/usr/bin/env python3
"""Import pinned upstream rules, preserving manual entries and attribution."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yaml

from rulelib import ROOT, RULE_TYPES, Rule, SourceError, iter_source_conflicts, load_policy, load_rules, normalize, read_yaml, validate_sources


def parse_line(line: str, format_name: str) -> tuple[str, str] | None:
    content = line.split("#", 1)[0].strip()
    if not content:
        return None
    if format_name == "classical":
        fields = content.split(",")
        if len(fields) < 2 or fields[0] not in RULE_TYPES:
            raise SourceError("unsupported-type")
        rule_type, value = fields[:2]
        if len(fields) > 2 and fields[2:] != ["no-resolve"]:
            raise SourceError("unsupported-option")
    elif format_name == "v2ray":
        value = content.split()[0]
        if ":" in value:
            kind, value = value.split(":", 1)
            rule_type = {"full": "DOMAIN", "domain": "DOMAIN-SUFFIX", "keyword": "DOMAIN-KEYWORD"}.get(kind)
            if not rule_type:
                raise SourceError("unsupported-type")
        else:
            rule_type = "DOMAIN-SUFFIX"
    else:
        raise SourceError("unknown-source-format")
    if rule_type == "GEOIP" and value.upper() == "CN":
        raise SourceError("generated-geoip-cn-tail")
    try:
        return rule_type, normalize(rule_type, value)
    except SourceError as exc:
        raise SourceError("invalid-value") from exc


def fetch_snapshot(repo: dict, path: str, cache_dir: Path | None, offline: bool) -> bytes:
    if not re.fullmatch(r"[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+", repo["repository"]) or not re.fullmatch(r"[a-f0-9]{40}", repo["commit"]):
        raise SourceError("上游必须是合法 GitHub owner/repo 和完整提交 SHA")
    if not re.fullmatch(r"[a-zA-Z0-9_./!-]+", path) or ".." in path or path.startswith("/"):
        raise SourceError("非法上游文件路径")
    # Cache keys include the repository, exact commit and complete path.
    key = hashlib.sha256(f"{repo['repository']}@{repo['commit']}/{path}".encode()).hexdigest()
    cached = cache_dir / key if cache_dir else None
    if cached and cached.exists():
        return cached.read_bytes()
    if offline:
        raise SourceError(f"缓存中缺少固定来源：{repo['repository']}/{path}")
    with urlopen(f"https://raw.githubusercontent.com/{repo['repository']}/{repo['commit']}/{path}", timeout=30) as response:
        raw = response.read()
    if cached:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(raw)
    return raw


def collect_sources(spec: dict, cache_dir: Path | None, offline: bool, expected: dict | None = None):
    """Resolve v2fly includes and collect provenance without touching rules/."""
    repositories = spec["repositories"]
    pending, visited, records = list(spec["sources"]), set(), []
    while pending:
        batch, pending = pending, []
        unique = []
        for source in batch:
            identity = (source["repository"], source["category"], source["path"])
            if identity not in visited:
                visited.add(identity)
                unique.append(source)
        with ThreadPoolExecutor(max_workers=4) as pool:
            snapshots = list(pool.map(lambda source: fetch_snapshot(repositories[source["repository"]], source["path"], cache_dir, offline), unique))
        for source, raw in zip(unique, snapshots):
            repo = repositories[source["repository"]]
            expected_hash = (expected or {}).get((repo["repository"], repo["commit"], source["path"]))
            if expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash:
                raise SourceError(f"固定来源摘要变化：{source['path']}；未使用该内容")
            record = {**source, "sha256": hashlib.sha256(raw).hexdigest(), "selected": [], "skipped": {}, "skipped_examples": {}}
            candidates, skipped = [], Counter()
            for line in raw.decode("utf-8").splitlines():
                content = line.split("#", 1)[0].strip()
                if not content:
                    continue
                if repo["format"] == "v2ray" and content.startswith("include:"):
                    fields = content.split()
                    if len(fields) != 1 or "@" in fields[0]:
                        raise SourceError(f"不支持带属性筛选的 include：{source['path']} / {content}")
                    pending.append({**source, "path": "data/" + fields[0].removeprefix("include:")})
                    continue
                # v2fly's @ads entries belong in the rejection category.
                if repo["format"] == "v2ray" and "@ads" in content.split():
                    skipped["advertising-attribute"] += 1
                    continue
                try:
                    parsed = parse_line(line, repo["format"])
                except SourceError as exc:
                    reason = str(exc)
                    skipped[reason] += 1
                    examples = record["skipped_examples"].setdefault(reason, [])
                    if len(examples) < 5:
                        examples.append(line)
                    continue
                if parsed:
                    if source.get("only_values") and parsed[1] not in source["only_values"]:
                        skipped["outside-selected-scope"] += 1
                        continue
                    if parsed[1] in source.get("exclude_values", []):
                        skipped["assigned-to-other-category"] += 1
                        continue
                    candidates.append((line, Rule(*parsed, comment=f"upstream:{source['repository']}:{source['path']}")))
            record["skipped"] = dict(skipped)
            record["upstream_rules"] = len(candidates) + sum(skipped.values())
            records.append((record, candidates))
    return records


def prepare_import(spec: dict, existing: dict, order: list[str], cache_dir: Path | None, offline: bool, expected: dict | None = None):
    records = collect_sources(spec, cache_dir, offline, expected)
    # Source-tagged entries are replaceable. Untagged/user comments are retained.
    manual = {category: [rule for rule in rules if not rule.comment.startswith(("upstream:", "blackmatrix7/", "v2fly/"))] for category, rules in existing.items()}
    by_category = defaultdict(list)
    for record, candidates in records:
        by_category[record["category"]].append((record, candidates))
    seen, categories = {}, {}
    for category in order:
        rules = []
        for rule in manual.get(category, []):
            key = (rule.type, rule.value)
            if key in seen:
                raise SourceError(f"手工规则重复或被更高优先级分类覆盖：{category} / {rule.line}")
            seen[key] = category
            rules.append(rule)
        for record, candidates in by_category[category]:
            for raw_line, rule in candidates:
                key = (rule.type, rule.value)
                if key in seen:
                    reason = "duplicate-same-category" if seen[key] == category else "owned-by-higher-category"
                    record["skipped"][reason] = record["skipped"].get(reason, 0) + 1
                    continue
                seen[key] = category
                rules.append(rule)
                record["selected"].append(raw_line)
        if not rules:
            raise SourceError(f"分类导入后为空：{category}")
        categories[category] = rules
    unknown = set(by_category) | set(existing)
    if unknown - set(order):
        raise SourceError(f"策略顺序遗漏分类：{sorted(unknown - set(order))}")
    manifest = {"version": 2, "repositories": spec["repositories"], "sources": [record for record, _ in records]}
    return categories, manifest


def overlap_report(categories: dict, order: list[str]) -> list[dict]:
    pairs = {}
    for kind, entry, prior in iter_source_conflicts(categories):
        if kind == "duplicate":
            raise SourceError("导入后仍有重复规则")
        high, low = sorted((entry[0], prior[0]), key=order.index)
        report = pairs.setdefault((high, low), {"higher": high, "lower": low, "count": 0, "examples": []})
        report["count"] += 1
        if len(report["examples"]) < 3:
            report["examples"].append([entry[1].line, prior[1].line])
    return list(pairs.values())


def main() -> int:
    parser = argparse.ArgumentParser(description="导入固定上游；默认只预览，--write 才写入")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    try:
        spec = read_yaml(ROOT / "upstream.yaml")
        policy_data = read_yaml(ROOT / "policy.yaml")
        existing = load_rules(ROOT / "rules")
        previous = read_yaml(ROOT / "sources.yaml")
        old_repos = previous.get("repositories", {"blackmatrix": {"repository": previous.get("repository", "").removeprefix("https://github.com/"), "commit": previous.get("commit", "")}})
        expected = {(old_repos[item.get("repository", "blackmatrix")]["repository"], old_repos[item.get("repository", "blackmatrix")]["commit"], item["path"]): item["sha256"] for item in previous["sources"]}
        categories, manifest = prepare_import(spec, existing, policy_data["category_order"], args.cache_dir, args.offline, expected)
        policy = load_policy(ROOT / "policy.yaml", categories)
        report = overlap_report(categories, policy["category_order"])
        summary = {"categories": {name: len(rules) for name, rules in categories.items()}, "total": sum(map(len, categories.values())), "overlaps": report}
        if args.report:
            args.report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if args.write:
            errors = validate_sources(categories, policy)
            if errors:
                raise SourceError("尚有未声明的跨分类覆盖；未写入。\n" + "\n".join(errors[:20]))
            for category, rules in categories.items():
                entries = [{"type": r.type, "value": r.value, "comment": r.comment} for r in rules]
                (ROOT / "rules" / f"{category}.yaml").write_text(yaml.safe_dump(entries, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
            (ROOT / "sources.yaml").write_text(yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
            print("已写入规则和来源清单；手工规则保留。")
    except (SourceError, OSError, KeyError, ValueError) as exc:
        print(f"导入失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
