import copy
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from build import SUB_PLACEHOLDER, build, clash_config
from rulelib import ROOT, Rule, SourceError, load_sources


@pytest.fixture(scope="module")
def artifacts(tmp_path_factory):
    output = tmp_path_factory.mktemp("public-artifacts") / "dist"
    build(ROOT / "rules", ROOT / "policy.yaml", output)
    return output


def test_every_category_round_trips_in_both_formats(artifacts, source_bundle):
    categories, policy = source_bundle
    config = yaml.safe_load((artifacts / "clash/config.yaml").read_text())
    for category, rules in categories.items():
        sr = (artifacts / f"shadowrocket/{category}.list").read_text().splitlines()
        actual_sr = [line for line in sr if line and not line.startswith("#")]
        assert actual_sr == [rule.line for rule in rules]
        domain_rules = [rule for rule in rules if rule.type in {"DOMAIN", "DOMAIN-SUFFIX"}]
        classical_rules = [rule for rule in rules if rule.type not in {"DOMAIN", "DOMAIN-SUFFIX"}]
        if domain_rules:
            provider = yaml.safe_load((artifacts / f"clash/{category}_domain.yaml").read_text())
            assert provider["payload"] == [rule.value if rule.type == "DOMAIN" else f".{rule.value}" for rule in domain_rules]
            spec = config["rule-providers"][f"{category}_domain"]
            assert spec["behavior"] == "domain"
            assert spec["url"] == f"{policy['rule_base_url']}/clash/{category}_domain.yaml"
        if classical_rules:
            provider = yaml.safe_load((artifacts / f"clash/{category}.yaml").read_text())
            assert provider["payload"] == [rule.line for rule in classical_rules]
            spec = config["rule-providers"][category]
            assert spec["behavior"] == "classical"
            assert spec["url"] == f"{policy['rule_base_url']}/clash/{category}.yaml"


@pytest.mark.parametrize("rule_type,value,expected", [
    ("DOMAIN", "example.com", "DOMAIN,example.com"),
    ("DOMAIN-SUFFIX", "example.com", "DOMAIN-SUFFIX,example.com"),
    ("DOMAIN-KEYWORD", "example", "DOMAIN-KEYWORD,example"),
    ("IP-CIDR", "192.0.2.0/24", "IP-CIDR,192.0.2.0/24,no-resolve"),
    ("IP-CIDR6", "2001:db8::/32", "IP-CIDR6,2001:db8::/32,no-resolve"),
    ("GEOIP", "US", "GEOIP,US"),
])
def test_all_types_written_to_both_formats(tmp_path, rule_type, value, expected, source_bundle):
    categories, _ = source_bundle
    rules_dir = tmp_path / "sources"
    rules_dir.mkdir()
    for category, rules in categories.items():
        entries = [{"type": r.type, "value": r.value} for r in rules[:1]]
        if category == "ai":
            entries.append({"type": rule_type, "value": value, "comment": "first\nsecond"})
        (rules_dir / f"{category}.yaml").write_text(yaml.safe_dump(entries))
    output = tmp_path / "out"
    build(rules_dir, ROOT / "policy.yaml", output)
    assert expected in (output / "shadowrocket/ai.list").read_text().splitlines()
    if rule_type in {"DOMAIN", "DOMAIN-SUFFIX"}:
        domain_rules = yaml.safe_load((output / "clash/ai_domain.yaml").read_text())["payload"]
        assert (value if rule_type == "DOMAIN" else f".{value}") in domain_rules
    else:
        classical = yaml.safe_load((output / "clash/ai.yaml").read_text())["payload"]
        assert expected in classical
    assert "# first second" in (output / "shadowrocket/ai.list").read_text()


def test_order_group_references_and_terminal_rules(artifacts, source_bundle):
    _, policy = source_bundle
    sr_text = (artifacts / "shadowrocket/shadowrocket.conf").read_text()
    sr_rules = [line for line in sr_text.split("[Rule]\n")[1].splitlines() if not line.startswith("#")]
    config = yaml.safe_load((artifacts / "clash/config.yaml").read_text())
    assert sr_rules == [
        f"RULE-SET,{policy['rule_base_url']}/shadowrocket/{name}.list,{policy['categories'][name]}"
        for name in policy["category_order"]
    ] + ["GEOIP,CN,DIRECT", "FINAL,节点选择"]
    expected_rules = []
    for name in policy["category_order"]:
        if (artifacts / f"clash/{name}_domain.yaml").exists():
            expected_rules.append(f"RULE-SET,{name}_domain,{policy['categories'][name]}")
        if (artifacts / f"clash/{name}.yaml").exists():
            expected_rules.append(f"RULE-SET,{name},{policy['categories'][name]}")
    assert config["rules"] == expected_rules + ["GEOIP,CN,DIRECT", "MATCH,节点选择"]
    assert sr_rules[0].endswith("ads_reject.list,REJECT")
    assert sr_rules[-3].endswith("cn_direct.list,DIRECT")
    names = {group["name"] for group in config["proxy-groups"]}
    assert names == {"节点选择"}
    for group in config["proxy-groups"]:
        assert set(group["proxies"]) <= names | {"DIRECT", "REJECT"}
        if group.get("use"):
            assert group["use"] == ["subscription"]
    assert config["dns"]["enhanced-mode"] == "fake-ip"
    assert config["dns"]["fake-ip-range"] == "198.18.0.1/16"
    assert config["geodata-mode"] is True
    assert config["dns"]["respect-rules"] is True
    assert config["dns"]["nameserver-policy"]["geosite:cn"] == ["https://dns.alidns.com/dns-query#DIRECT", "https://doh.pub/dns-query#DIRECT"]
    assert config["dns"]["nameserver-policy"]["geosite:geolocation-!cn"] == ["https://cloudflare-dns.com/dns-query#节点选择", "https://dns.google/dns-query#节点选择"]
    assert config["rules"].index("RULE-SET,microsoft_domain,DIRECT") < config["rules"].index("RULE-SET,global_proxy_domain,节点选择")
    assert "[General]" in sr_text and "[Proxy Group]" in sr_text
    assert sr_text.split("[Proxy]\n")[1].split("[Proxy Group]")[0].strip().startswith("#")
    assert "节点选择 = select, DIRECT, policy-regex-filter=" in sr_text


def test_public_build_never_embeds_subscription(tmp_path, monkeypatch):
    private_url = "https://subscription.invalid/private-test-token"
    monkeypatch.setenv("SUB_URL", private_url)
    output = tmp_path / "public"
    build(ROOT / "rules", ROOT / "policy.yaml", output)
    config = yaml.safe_load((output / "clash/config.yaml").read_text())
    assert config["proxy-providers"]["subscription"]["url"] == SUB_PLACEHOLDER
    for path in output.rglob("*"):
        if path.is_file():
            assert private_url not in path.read_text()


def test_private_rendering_and_repository_guard(tmp_path, monkeypatch):
    monkeypatch.setenv("SUB_URL", "https://subscription.invalid/private-test-token")
    output = tmp_path / "private"
    build(ROOT / "rules", ROOT / "policy.yaml", output, subscription=True)
    config = yaml.safe_load((output / "clash/config.yaml").read_text())
    assert config["proxy-providers"]["subscription"]["url"] == "https://subscription.invalid/private-test-token"
    with pytest.raises(SourceError, match="私人目录"):
        build(ROOT / "rules", ROOT / "policy.yaml", ROOT / "dist", subscription=True)
    monkeypatch.delenv("SUB_URL")
    with pytest.raises(SourceError, match="SUB_URL"):
        build(ROOT / "rules", ROOT / "policy.yaml", output, subscription=True)


def test_build_is_deterministic_and_preserves_unrelated_files(artifacts):
    before = {p.relative_to(artifacts): p.read_bytes() for p in artifacts.rglob("*") if p.is_file()}
    unrelated = artifacts / "clash/user-config.yaml"
    unrelated.write_text("user: retained\n")
    build(ROOT / "rules", ROOT / "policy.yaml", artifacts)
    for name, data in before.items():
        assert (artifacts / name).read_bytes() == data
    assert unrelated.read_text() == "user: retained\n"
    assert (artifacts / "LICENSE").exists()
    assert (artifacts / "sources.yaml").exists()


def test_default_source_paths_work_outside_checkout(tmp_path):
    result = subprocess.run(
        [sys.executable, str(ROOT / "build.py"), "--output", str(tmp_path / "generated")],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "generated/shadowrocket/shadowrocket.conf").exists()


def test_generated_config_does_not_mutate_policy(source_bundle):
    _, policy = source_bundle
    original = copy.deepcopy(policy)
    clash_config(policy)
    assert policy == original


@pytest.mark.skipif(not shutil.which("mihomo"), reason="Mihomo compiler is not installed")
def test_mrs_build_emits_binary_domain_providers(tmp_path):
    output = tmp_path / "mrs-dist"
    build(ROOT / "rules", ROOT / "policy.yaml", output, mrs=True)
    config = yaml.safe_load((output / "clash/config.yaml").read_text())
    domain_providers = [provider for provider in config["rule-providers"].values() if provider["behavior"] == "domain"]
    assert len(domain_providers) > 0
    assert all(provider["format"] == "mrs" for provider in domain_providers)
    for provider in domain_providers:
        name = Path(provider["url"]).name
        binary = output / "clash" / name
        assert binary.exists() and binary.stat().st_size > 4
        assert binary.read_bytes().startswith(bytes.fromhex("28b52ffd"))


def test_x_core_services_and_grok_have_explicit_routing(artifacts):
    config = yaml.safe_load((artifacts / "clash/config.yaml").read_text())
    x_payload = yaml.safe_load((artifacts / "clash/x_domain.yaml").read_text())["payload"]
    essential = {f".{domain}" for domain in (
        "x.com", "twitter.com", "t.co", "twimg.com", "twvid.com", "twitteroauth.com"
    )}
    assert essential <= set(x_payload)
    assert "RULE-SET,x_domain,节点选择" in config["rules"]
    assert config["rules"].index("RULE-SET,x_domain,节点选择") < config["rules"].index("RULE-SET,cn_direct_domain,DIRECT")
    assert not any(group["name"] == "X" for group in config["proxy-groups"])
    sr = (artifacts / "shadowrocket/shadowrocket.conf").read_text()
    assert "X = select, 节点选择, 自动测速, DIRECT" not in sr
    assert "/shadowrocket/x.list,节点选择" in sr
    ai_payload = yaml.safe_load((artifacts / "clash/ai_domain.yaml").read_text())["payload"]
    assert ".grok.com" in ai_payload
    assert "DOMAIN-SUFFIX,grok.com" not in x_payload
