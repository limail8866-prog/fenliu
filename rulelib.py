"""Shared, strict source loading and routing validation (Python 3.11)."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parent
RULE_TYPES = {"DOMAIN", "DOMAIN-SUFFIX", "DOMAIN-KEYWORD", "IP-CIDR", "IP-CIDR6", "GEOIP"}
DOMAIN_TYPES = {"DOMAIN", "DOMAIN-SUFFIX"}
IP_TYPES = {"IP-CIDR", "IP-CIDR6"}


class SourceError(ValueError):
    """An actionable, non-secret source validation error."""


class UniqueKeyLoader(getattr(yaml, "CSafeLoader", yaml.SafeLoader)):
    pass


def _mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, (str, int)):
            raise SourceError("YAML 字典键必须是字符串或整数")
        if key in result:
            raise SourceError(f"YAML 字典键重复：{key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapping)


def read_yaml(path: Path):
    try:
        return yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeyLoader)
    except (OSError, yaml.YAMLError, SourceError) as exc:
        raise SourceError(f"{path.name}: 无法读取合法 YAML：{exc}") from exc


def https_url(value: object) -> bool:
    if not isinstance(value, str) or any(c.isspace() for c in value):
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme == "https" and bool(parsed.hostname) and parsed.port != 0
    except ValueError:
        return False


def normalize(rule_type: str, value: str) -> str:
    if not value or value != value.strip() or any(c in value for c in ",\r\n#"):
        raise SourceError("value 不能为空或包含空白边界、逗号、换行、#")
    if rule_type in DOMAIN_TYPES:
        try:
            domain = value.encode("idna").decode("ascii").lower()
        except UnicodeError as exc:
            raise SourceError("非法域名编码") from exc
        labels = domain.split(".")
        if len(domain) > 253 or len(labels) < 2 or any(
            not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
            for label in labels
        ):
            raise SourceError(f"非法域名：{value}")
        try:
            ipaddress.ip_address(domain)
        except ValueError:
            return domain
        raise SourceError("域名规则不能填写 IP 地址")
    if rule_type in IP_TYPES:
        if "/" not in value:
            raise SourceError("CIDR 必须显式包含 /前缀长度")
        try:
            network = ipaddress.ip_network(value, strict=True)
        except ValueError as exc:
            raise SourceError(f"非法 CIDR：{value}") from exc
        if network.version != (4 if rule_type == "IP-CIDR" else 6):
            raise SourceError(f"{rule_type} 与 IP 版本不匹配")
        return str(network)
    if rule_type == "DOMAIN-KEYWORD":
        if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]*", value):
            raise SourceError("DOMAIN-KEYWORD 只接受 ASCII 字母、数字、点、下划线和连字符")
        return value.lower()
    if rule_type == "GEOIP":
        if not re.fullmatch(r"[A-Za-z]{2}", value):
            raise SourceError("GEOIP 必须是两位国家/地区代码")
        return value.upper()
    raise SourceError(f"不支持的规则类型：{rule_type}")


@dataclass(frozen=True)
class Rule:
    type: str
    value: str
    comment: str = ""

    @property
    def line(self) -> str:
        suffix = ",no-resolve" if self.type in IP_TYPES else ""
        return f"{self.type},{self.value}{suffix}"


def load_rules(directory: Path) -> dict[str, list[Rule]]:
    paths = sorted(directory.glob("*.yaml"))
    if not paths:
        raise SourceError(f"{directory}: 未找到分类 YAML")
    categories = {}
    for path in paths:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", path.stem):
            raise SourceError(f"{path.name}: 非法分类名")
        data = read_yaml(path)
        if not isinstance(data, list) or not data:
            raise SourceError(f"{path.name}: 分类必须是非空规则列表")
        rules = []
        for index, entry in enumerate(data, 1):
            location = f"{path.name}:第 {index} 条"
            try:
                if not isinstance(entry, dict) or set(entry) - {"type", "value", "comment"}:
                    raise SourceError("规则必须是仅含 type、value、可选 comment 的字典")
                if entry.get("type") not in RULE_TYPES:
                    raise SourceError("未知或缺失 type")
                if not isinstance(entry.get("value"), str):
                    raise SourceError("value 必须是字符串；GEOIP 的 NO 等值须加引号")
                if not isinstance(entry.get("comment", ""), str):
                    raise SourceError("comment 必须是字符串")
                comment = " ".join(entry.get("comment", "").splitlines())
                rules.append(Rule(entry["type"], normalize(entry["type"], entry["value"]), comment))
            except (SourceError, TypeError) as exc:
                raise SourceError(f"{location}: {exc}") from exc
        categories[path.stem] = rules
    return categories


def _safe_group_name(name: object) -> bool:
    return isinstance(name, str) and bool(name) and name == name.strip() and not any(c in name for c in ",\r\n\t=#[]")


def load_policy(path: Path, categories: dict[str, list[Rule]]) -> dict:
    data = read_yaml(path)
    required = {"version", "rule_base_url", "groups", "categories", "category_order", "final"}
    if not isinstance(data, dict) or not required <= set(data) or set(data) - required - {"overrides"} or type(data["version"]) is not int or data["version"] != 1:
        raise SourceError("policy.yaml 字段或 version 不合法")
    if not https_url(data["rule_base_url"]) or any(c in data["rule_base_url"] for c in ",#"):
        raise SourceError("rule_base_url 必须是合法 HTTPS 地址")
    base = urlsplit(data["rule_base_url"])
    if base.username or base.password or base.query or base.fragment:
        raise SourceError("rule_base_url 不接受凭据、查询参数或片段")
    groups = data["groups"]
    if not isinstance(groups, list) or not groups:
        raise SourceError("groups 必须是非空列表")
    names = []
    for group in groups:
        if not isinstance(group, dict) or not _safe_group_name(group.get("name")):
            raise SourceError("非法策略组名称")
        if group["name"] in {"DIRECT", "REJECT"} or group["name"] in names:
            raise SourceError(f"策略组名称重复或与内置策略冲突：{group['name']}")
        names.append(group["name"])
    for group in groups:
        allowed = {"name", "type", "proxies", "use", "url", "interval", "tolerance"}
        if set(group) - allowed or group.get("type") not in ("select", "url-test"):
            raise SourceError(f"{group['name']}: 非法策略组字段或类型")
        proxies = group.get("proxies")
        if not isinstance(proxies, list) or (not proxies and not group.get("use")) or any(
            p not in names + ["DIRECT", "REJECT"] for p in proxies
        ):
            raise SourceError(f"{group['name']}: proxies 必须引用已定义策略组或 DIRECT/REJECT")
        if len(set(proxies)) != len(proxies) or group.get("use", []) not in ([], ["subscription"]):
            raise SourceError(f"{group['name']}: 重复 proxies 或未知 provider")
        if group["type"] == "url-test":
            if not https_url(group.get("url")) or any(c in group["url"] for c in ",#"):
                raise SourceError(f"{group['name']}: url-test 需要合法 HTTPS 测速 URL")
            for key in ("interval", "tolerance"):
                if type(group.get(key)) is not int or group[key] < (1 if key == "interval" else 0):
                    raise SourceError(f"{group['name']}: {key} 必须是合法整数")
        elif set(group) & {"url", "interval", "tolerance"}:
            raise SourceError(f"{group['name']}: select 不接受测速参数")
    graph = {g["name"]: [p for p in g["proxies"] if p in names] for g in groups}

    def visit(name, active, done):
        if name in active:
            raise SourceError(f"策略组循环引用：{name}")
        if name in done:
            return
        for child in graph[name]:
            visit(child, active | {name}, done)
        done.add(name)

    done = set()
    for name in names:
        visit(name, set(), done)
    mapping, order = data["categories"], data["category_order"]
    if not isinstance(mapping, dict) or set(mapping) != set(categories):
        raise SourceError("categories 必须恰好映射 rules/ 中的全部分类")
    if any(target not in names for target in mapping.values()) or data["final"] not in names:
        raise SourceError("分类或 final 引用了不存在的策略组")
    if not isinstance(order, list) or any(not isinstance(c, str) for c in order) or len(order) != len(categories) or set(order) != set(categories):
        raise SourceError("category_order 必须包含每个分类且不重复")
    if order[0] != "ads_reject" or order[-1] != "cn_direct":
        raise SourceError("分类顺序必须以 ads_reject 开头、cn_direct 结尾")
    by_name = {g["name"]: g for g in groups}
    for category, builtin in (("ads_reject", "REJECT"), ("cn_direct", "DIRECT")):
        group = by_name[mapping[category]]
        if group["proxies"] != [builtin] or group.get("use") or group["type"] != "select":
            raise SourceError(f"{category} 必须映射到仅包含 {builtin} 的 select 策略组")
    overrides = data.get("overrides", [])
    if not isinstance(overrides, list):
        raise SourceError("overrides 必须是列表")
    pairs = set()
    for override in overrides:
        if not isinstance(override, dict) or set(override) != {"higher", "lower", "reason"}:
            raise SourceError("overrides 条目需要 higher、lower 和 reason")
        higher, lower = override["higher"], override["lower"]
        if higher not in order or lower not in order or order.index(higher) >= order.index(lower):
            raise SourceError("overrides 必须引用存在的分类且 higher 排在 lower 前")
        if not isinstance(override["reason"], str) or not override["reason"].strip():
            raise SourceError("overrides 必须说明覆盖原因")
        if (higher, lower) in pairs:
            raise SourceError("overrides 分类对重复")
        pairs.add((higher, lower))
    return data


def overlaps(left: Rule, right: Rule) -> bool:
    if left.type == right.type and left.value == right.value:
        return True
    if left.type in DOMAIN_TYPES and right.type in DOMAIN_TYPES:
        def matches(suffix, domain):
            return domain == suffix or domain.endswith("." + suffix)
        return ((left.type == "DOMAIN-SUFFIX" and matches(left.value, right.value)) or
                (right.type == "DOMAIN-SUFFIX" and matches(right.value, left.value)))
    if left.type == "DOMAIN-KEYWORD" and right.type in DOMAIN_TYPES:
        return left.value in right.value
    if right.type == "DOMAIN-KEYWORD" and left.type in DOMAIN_TYPES:
        return right.value in left.value
    if left.type == right.type == "DOMAIN-KEYWORD":
        return left.value in right.value or right.value in left.value
    if left.type in IP_TYPES and right.type == left.type:
        return ipaddress.ip_network(left.value).overlaps(ipaddress.ip_network(right.value))
    return False


def iter_source_conflicts(categories: dict[str, list[Rule]]):
    """Yield duplicates and overlaps using domain indexes and CIDR intervals.

    Never compare every pair of domains: suffix lookup is proportional to label
    count; keyword scanning is proportional to the small keyword rule count.
    """
    seen, entries = {}, []
    for category, rules in categories.items():
        for index, rule in enumerate(rules, 1):
            location = f"{category}.yaml:第 {index} 条"
            key = (rule.type, rule.value)
            if key in seen:
                prior = seen[key]
                yield "duplicate", (category, rule, location), prior
            else:
                entry = (category, rule, location)
                seen[key] = entry
                entries.append(entry)
    suffixes = {entry[1].value: entry for entry in entries if entry[1].type == "DOMAIN-SUFFIX"}
    domains = [entry for entry in entries if entry[1].type in DOMAIN_TYPES]
    keywords = [entry for entry in entries if entry[1].type == "DOMAIN-KEYWORD"]
    for entry in domains:
        category, rule, _ = entry
        labels = rule.value.split(".")
        for index in range(len(labels)):
            suffix = suffixes.get(".".join(labels[index:]))
            if suffix and suffix[0] != category:
                # The same-value DOMAIN + DOMAIN-SUFFIX pair is reported once,
                # and suffix children discover their unique ancestor naturally.
                yield "overlap", entry, suffix
        for keyword in keywords:
            if keyword[0] != category and keyword[1].value in rule.value:
                yield "overlap", entry, keyword
    for index, keyword in enumerate(keywords):
        for prior in keywords[:index]:
            if prior[0] != keyword[0] and overlaps(prior[1], keyword[1]):
                yield "overlap", keyword, prior
    for ip_type in IP_TYPES:
        networks = []
        for entry in entries:
            if entry[1].type == ip_type:
                network = ipaddress.ip_network(entry[1].value)
                networks.append((int(network.network_address), int(network.broadcast_address), entry))
        active = []
        for start, end, entry in sorted(networks, key=lambda n: (n[0], -n[1])):
            active = [(prior_end, prior) for prior_end, prior in active if prior_end >= start]
            for _, prior in active:
                if prior[0] != entry[0]:
                    yield "overlap", entry, prior
            active.append((end, entry))


def validate_sources(categories: dict[str, list[Rule]], policy: dict | None = None) -> list[str]:
    overrides = {frozenset((item["higher"], item["lower"])) for item in (policy or {}).get("overrides", [])}
    errors = []
    for kind, entry, prior in iter_source_conflicts(categories):
        category, rule, location = entry
        prior_category, prior_rule, prior_location = prior
        if kind == "duplicate":
            errors.append(f"重复规则：{location} 与 {prior_location} ({rule.line})")
        elif frozenset((category, prior_category)) not in overrides:
            errors.append(f"跨分类冲突：{location} 与 {prior_location} ({rule.line} / {prior_rule.line})")
    return errors


def load_sources(rules_dir: Path = ROOT / "rules", policy_path: Path = ROOT / "policy.yaml"):
    categories = load_rules(rules_dir)
    policy = load_policy(policy_path, categories)
    errors = validate_sources(categories, policy)
    if errors:
        raise SourceError("\n".join(errors))
    return categories, policy
