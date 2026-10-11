#!/usr/bin/env python3
"""Build public rule artifacts; private subscription rendering is explicit."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

import yaml

from rulelib import ROOT, SourceError, https_url, load_sources

SUB_PLACEHOLDER = "${SUB_URL}"


def dump_yaml(data: dict) -> str:
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def shadowrocket_config(policy: dict) -> str:
    lines = [
        "# 自动生成；源文件：rules/*.yaml + policy.yaml",
        "# 节点订阅请在 Shadowrocket 首页自行导入；此配置不包含节点。",
        "[General]",
        "bypass-system = true",
        "skip-proxy = 127.0.0.1, localhost, *.local, 192.168.0.0/16, 10.0.0.0/8, 172.16.0.0/12",
        "dns-server = system, 223.5.5.5, 119.29.29.29",
        "ipv6 = true",
        "",
        "[Proxy]",
        "# 留空；节点由用户在客户端导入。",
        "",
        "[Proxy Group]",
    ]
    for group in policy["groups"]:
        options = [group["type"], *group["proxies"]]
        if group.get("use"):
            # Shadowrocket selects imported subscription nodes via policy-regex-filter.
            options.append("policy-regex-filter=^(?!DIRECT$|REJECT$).+")
        if group["type"] == "url-test":
            options += [f"url={group['url']}", f"interval={group['interval']}", f"tolerance={group['tolerance']}"]
        lines.append(f"{group['name']} = {', '.join(options)}")
    lines += ["", "[Rule]", "# 拒绝 > 分类分流 > 国内直连 > GEOIP,CN > 漏网之鱼"]
    base = policy["rule_base_url"].rstrip("/")
    for category in policy["category_order"]:
        lines.append(f"RULE-SET,{base}/shadowrocket/{category}.list,{policy['categories'][category]}")
    lines += ["GEOIP,CN,DIRECT", f"FINAL,{policy['final']}"]
    return "\n".join(lines) + "\n"


def clash_config(policy: dict, subscription_url: str = SUB_PLACEHOLDER) -> dict:
    base = policy["rule_base_url"].rstrip("/")
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": True,
        "dns": {
            "enable": True,
            "listen": "127.0.0.1:1053",
            "ipv6": True,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": ["*.lan", "*.local", "localhost", "+.msftconnecttest.com", "+.msftncsi.com"],
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "nameserver": ["https://dns.alidns.com/dns-query", "https://doh.pub/dns-query"],
            "proxy-server-nameserver": ["https://dns.alidns.com/dns-query"],
        },
        "proxy-providers": {
            "subscription": {
                "type": "http",
                "url": subscription_url,
                "path": "./providers/subscription.yaml",
                "interval": 86400,
                "health-check": {"enable": True, "url": "https://www.gstatic.com/generate_204", "interval": 300},
            }
        },
        "proxy-groups": policy["groups"],
        "rule-providers": {
            category: {
                "type": "http",
                "behavior": "classical",
                "format": "yaml",
                "url": f"{base}/clash/{category}.yaml",
                "path": f"./rules/{category}.yaml",
                "interval": 86400,
            }
            for category in policy["category_order"]
        },
        "rules": [
            f"RULE-SET,{category},{policy['categories'][category]}"
            for category in policy["category_order"]
        ] + ["GEOIP,CN,DIRECT", f"MATCH,{policy['final']}"],
    }
    return config


def build(rules_dir: Path, policy_path: Path, output: Path, *, subscription: bool = False) -> dict:
    categories, policy = load_sources(rules_dir, policy_path)
    subscription_url = SUB_PLACEHOLDER
    if subscription:
        if output.resolve().is_relative_to(ROOT):
            raise SourceError("含订阅地址的配置必须输出到仓库外的私人目录")
        subscription_url = os.environ.get("SUB_URL", "")
        if not https_url(subscription_url):
            raise SourceError("请通过 SUB_URL 环境变量提供合法 HTTPS 订阅地址；不要提交地址")
    sr_dir, clash_dir = output / "shadowrocket", output / "clash"
    sr_dir.mkdir(parents=True, exist_ok=True)
    clash_dir.mkdir(parents=True, exist_ok=True)
    for category in policy["category_order"]:
        rules = categories[category]
        lines = [f"# {category} | 自动生成；请修改 rules/{category}.yaml"]
        for rule in rules:
            if rule.comment:
                lines.append(f"# {rule.comment}")
            lines.append(rule.line)
        (sr_dir / f"{category}.list").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (clash_dir / f"{category}.yaml").write_text(dump_yaml({"payload": [rule.line for rule in rules]}), encoding="utf-8")
    (sr_dir / "shadowrocket.conf").write_text(shadowrocket_config(policy), encoding="utf-8")
    header = "# 自动生成；公开模板中的 ${SUB_URL} 必须由用户在本地替换。\n"
    (clash_dir / "config.yaml").write_text(header + dump_yaml(clash_config(policy, subscription_url)), encoding="utf-8")
    # Attribution accompanies published dist artifacts as well as source code.
    for name in ("LICENSE", "SOURCES.md", "sources.yaml", "upstream.yaml"):
        source = ROOT / name
        if source.exists():
            (output / name).write_bytes(source.read_bytes())
    if (ROOT / "licenses").exists():
        shutil.copytree(ROOT / "licenses", output / "licenses", dirs_exist_ok=True)
    (output / ".nojekyll").touch()
    return {"categories": len(categories), "rules": sum(map(len, categories.values()))}


def main() -> int:
    parser = argparse.ArgumentParser(description="生成 Shadowrocket / Mihomo 分流配置")
    parser.add_argument("--rules-dir", type=Path, default=ROOT / "rules")
    parser.add_argument("--policy", type=Path, default=ROOT / "policy.yaml")
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--subscription", action="store_true", help="读取 SUB_URL；必须输出到仓库外")
    args = parser.parse_args()
    try:
        summary = build(args.rules_dir, args.policy, args.output, subscription=args.subscription)
    except (SourceError, OSError) as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        return 1
    print(f"构建完成：{summary['categories']} 个分类，{summary['rules']} 条规则，输出到 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
