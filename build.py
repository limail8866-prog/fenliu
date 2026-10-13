#!/usr/bin/env python3
"""Build public rule artifacts; private subscription rendering is explicit."""

from __future__ import annotations

import argparse
import copy
import os
import shutil
import subprocess
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


DOMAIN_RULES = {"DOMAIN", "DOMAIN-SUFFIX"}


def domain_payload(rules) -> list[str]:
    return [rule.value if rule.type == "DOMAIN" else f".{rule.value}" for rule in rules if rule.type in DOMAIN_RULES]


def provider_specs(policy: dict, categories: dict | None, *, mrs: bool = False) -> dict:
    specs = {}
    for category in policy["category_order"]:
        rules = categories.get(category, []) if categories else []
        domains = domain_payload(rules)
        other_rules = [rule.line for rule in rules if rule.type not in DOMAIN_RULES]
        if categories is None or other_rules:
            specs[category] = {
                "behavior": "classical", "format": "yaml",
                "url": f"{policy['rule_base_url'].rstrip('/')}/clash/{category}.yaml",
                "path": f"./rules/{category}.yaml", "interval": 86400,
            }
        if domains:
            name = f"{category}_domain"
            suffix = "mrs" if mrs else "yaml"
            specs[name] = {
                "behavior": "domain", "format": suffix,
                "url": f"{policy['rule_base_url'].rstrip('/')}/clash/{name}.{suffix}",
                "path": f"./rules/{name}.{suffix}", "interval": 86400,
            }
    return specs


def clash_config(policy: dict, subscription_url: str = SUB_PLACEHOLDER, categories: dict | None = None, *, mrs: bool = False) -> dict:
    specs = provider_specs(policy, categories, mrs=mrs)
    config = {
        "mixed-port": 7890,
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "geodata-mode": True,
        "ipv6": True,
        "dns": {
            "enable": True,
            "listen": "127.0.0.1:1053",
            "ipv6": True,
            "enhanced-mode": "fake-ip",
            "fake-ip-range": "198.18.0.1/16",
            "fake-ip-filter": ["*.lan", "*.local", "localhost", "+.msftconnecttest.com", "+.msftncsi.com"],
            "default-nameserver": ["223.5.5.5", "119.29.29.29"],
            "respect-rules": True,
            "nameserver": ["https://dns.alidns.com/dns-query#DIRECT", "https://doh.pub/dns-query#DIRECT"],
            "nameserver-policy": {
                "geosite:cn": ["https://dns.alidns.com/dns-query#DIRECT", "https://doh.pub/dns-query#DIRECT"],
                "geosite:geolocation-!cn": ["https://cloudflare-dns.com/dns-query#节点选择", "https://dns.google/dns-query#节点选择"],
            },
            "proxy-server-nameserver": ["https://dns.alidns.com/dns-query#DIRECT"],
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
        "proxy-groups": copy.deepcopy(policy["groups"]),
        "rule-providers": {name: {"type": "http", **spec} for name, spec in specs.items()},
        "rules": [
            f"RULE-SET,{provider},{policy['categories'][category]}"
            for category in policy["category_order"]
            for provider in (f"{category}_domain", category)
            if provider in specs
        ] + ["GEOIP,CN,DIRECT", f"MATCH,{policy['final']}"],
    }
    return config


def clash_merge_config(policy: dict, categories: dict | None = None, *, mrs: bool = False) -> dict:
    """Clash Verge overlay: replace routing while retaining the active profile's nodes."""
    config = clash_config(policy, categories=categories, mrs=mrs)
    groups = config["proxy-groups"]
    for group in groups:
        if group.pop("use", None):
            group["include-all-proxies"] = True
            group["include-all-providers"] = True
    # Avoid overwriting providers or cached rules belonging to the original profile.
    providers = {
        f"fenliu_{name}": {**spec, "path": f"./rules/fenliu/{Path(spec['path']).name}"}
        for name, spec in config["rule-providers"].items()
    }
    rules = []
    for rule in config["rules"]:
        if rule.startswith("RULE-SET,"):
            _, name, target = rule.split(",", 2)
            rule = f"RULE-SET,fenliu_{name},{target}"
        rules.append(rule)
    return {
        "profile": {"store-selected": True},
        "geodata-mode": config["geodata-mode"],
        "dns": config["dns"],
        "proxy-groups": groups,
        "rule-providers": providers,
        "rules": rules,
    }


def build(rules_dir: Path, policy_path: Path, output: Path, *, subscription: bool = False, mrs: bool = False) -> dict:
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
        domain_rules = [rule for rule in rules if rule.type in DOMAIN_RULES]
        classical_rules = [rule for rule in rules if rule.type not in DOMAIN_RULES]
        if domain_rules:
            domain_name = f"{category}_domain"
            domain_path = clash_dir / f"{domain_name}.yaml"
            domain_path.write_text(dump_yaml({"payload": domain_payload(domain_rules)}), encoding="utf-8")
            if mrs:
                converter = shutil.which("mihomo")
                if not converter:
                    raise SourceError("--mrs 需要 mihomo 命令；请安装 Mihomo Meta 内核")
                subprocess.run([converter, "convert-ruleset", "domain", "yaml", str(domain_path), str(clash_dir / f"{domain_name}.mrs")], check=True)
        if classical_rules:
            (clash_dir / f"{category}.yaml").write_text(dump_yaml({"payload": [rule.line for rule in classical_rules]}), encoding="utf-8")
    (sr_dir / "shadowrocket.conf").write_text(shadowrocket_config(policy), encoding="utf-8")
    header = "# 自动生成；公开模板中的 ${SUB_URL} 必须由用户在本地替换。\n"
    (clash_dir / "config.yaml").write_text(header + dump_yaml(clash_config(policy, subscription_url, categories, mrs=mrs)), encoding="utf-8")
    merge_header = (
        "# Clash Verge Rev：订阅 → 全局扩展覆写配置（Merge），粘贴本文件完整内容。\n"
        "# 使用当前选中订阅的节点；无需填写订阅 URL，不合并其他订阅卡片。\n"
        "# 替换策略组、分流规则及 DNS 设置；保存后使用规则模式并选择实际节点。\n"
    )
    (clash_dir / "merge.yaml").write_text(
        merge_header + dump_yaml(clash_merge_config(policy, categories, mrs=mrs)), encoding="utf-8"
    )
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
    parser.add_argument("--mrs", action="store_true", help="使用 Mihomo 将域名规则集编译为 .mrs 二进制格式")
    args = parser.parse_args()
    try:
        summary = build(args.rules_dir, args.policy, args.output, subscription=args.subscription, mrs=args.mrs)
    except (SourceError, OSError, subprocess.CalledProcessError) as exc:
        print(f"构建失败：{exc}", file=sys.stderr)
        return 1
    print(f"构建完成：{summary['categories']} 个分类，{summary['rules']} 条规则，输出到 {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
