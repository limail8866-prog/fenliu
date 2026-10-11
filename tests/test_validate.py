import copy
import subprocess
import sys

import pytest
import yaml

from rulelib import ROOT, Rule, SourceError, load_policy, load_rules, load_sources, normalize, read_yaml, validate_sources


@pytest.mark.parametrize("rule_type,value", [
    ("DOMAIN", "https://example.com"),
    ("DOMAIN", "*.example.com"),
    ("DOMAIN-SUFFIX", ".example.com"),
    ("DOMAIN", "bad..example.com"),
    ("DOMAIN", "-bad.example.com"),
    ("DOMAIN", "bad_.example.com"),
    ("DOMAIN", "example.com."),
    ("DOMAIN", "127.0.0.1"),
    ("DOMAIN", "localhost"),
    ("DOMAIN", "a" * 64 + ".com"),
    ("IP-CIDR", "192.0.2.1/24"),
    ("IP-CIDR", "192.0.2.0/33"),
    ("IP-CIDR", "192.0.2.1"),
    ("IP-CIDR", "2001:db8::/32"),
    ("IP-CIDR6", "192.0.2.0/24"),
    ("IP-CIDR6", "2001:db8::/129"),
    ("GEOIP", "CHN"),
    ("DOMAIN-KEYWORD", "bad,value"),
    ("DOMAIN-KEYWORD", "bad value"),
])
def test_invalid_domain_and_network_formats(rule_type, value):
    with pytest.raises(SourceError):
        normalize(rule_type, value)


def test_normalization_detects_duplicate_spellings():
    assert normalize("DOMAIN", "EXAMPLE.COM") == "example.com"
    assert normalize("DOMAIN", "例子.测试") == "xn--fsqu00a.xn--0zwm56d"
    assert normalize("IP-CIDR6", "2001:0db8:0000::/32") == "2001:db8::/32"
    assert normalize("GEOIP", "cn") == "CN"
    entries = {"ai": [Rule("DOMAIN", normalize("DOMAIN", value)) for value in ["EXAMPLE.COM", "example.com"]]}
    assert "重复规则" in validate_sources(entries)[0]


@pytest.mark.parametrize("left,right", [
    (Rule("DOMAIN", "api.example.com"), Rule("DOMAIN-SUFFIX", "example.com")),
    (Rule("DOMAIN-SUFFIX", "api.example.com"), Rule("DOMAIN-SUFFIX", "example.com")),
    (Rule("DOMAIN", "example.com"), Rule("DOMAIN", "example.com")),
    (Rule("DOMAIN-KEYWORD", "example"), Rule("DOMAIN", "api.example.com")),
    (Rule("DOMAIN-KEYWORD", "example"), Rule("DOMAIN-KEYWORD", "example-api")),
    (Rule("IP-CIDR", "192.0.2.0/24"), Rule("IP-CIDR", "192.0.2.0/25")),
    (Rule("IP-CIDR6", "2001:db8::/32"), Rule("IP-CIDR6", "2001:db8::/48")),
    (Rule("GEOIP", "CN"), Rule("GEOIP", "CN")),
])
def test_cross_category_conflicts(left, right):
    assert validate_sources({"ai": [left], "cn_direct": [right]})


def test_suffix_matching_respects_label_boundaries():
    assert validate_sources({"ai": [Rule("DOMAIN-SUFFIX", "example.com")],
                             "cn_direct": [Rule("DOMAIN", "notexample.com")]}) == []


@pytest.mark.parametrize("content", [
    "- {type: DOMAIN, value: example.com, value: other.com}\n",
    "- {type: UNKNOWN, value: example.com}\n",
    "- {type: DOMAIN, value: example.com, target: DIRECT}\n",
    "- {type: DOMAIN, value: 123}\n",
    "- {type: GEOIP, value: NO}\n",
    "- {type: DOMAIN, value: example.com, comment: 1}\n",
    "[]\n", "rules: []\n", "- [broken\n",
])
def test_bad_yaml_and_rule_schema(tmp_path, content):
    (tmp_path / "ai.yaml").write_text(content)
    with pytest.raises(SourceError):
        load_rules(tmp_path)


@pytest.mark.parametrize("mutation", ["unknown_group", "duplicate_group", "cycle", "order", "missing_category", "reject", "direct", "url", "provider"])
def test_policy_errors(tmp_path, mutation):
    categories, original = load_sources()
    policy = copy.deepcopy(original)
    if mutation == "unknown_group":
        policy["categories"]["ai"] = "不存在的策略组"
    elif mutation == "duplicate_group":
        policy["groups"].append(copy.deepcopy(policy["groups"][0]))
    elif mutation == "cycle":
        policy["groups"][1]["proxies"] = ["节点选择"]
    elif mutation == "order":
        policy["category_order"].reverse()
    elif mutation == "missing_category":
        del policy["categories"]["ai"]
    elif mutation == "reject":
        policy["categories"]["ads_reject"] = "直连"
    elif mutation == "direct":
        policy["categories"]["cn_direct"] = "节点选择"
    elif mutation == "url":
        policy["rule_base_url"] = "http://example.com"
    elif mutation == "provider":
        policy["groups"][0]["use"] = ["unknown"]
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(policy, allow_unicode=True))
    with pytest.raises(SourceError):
        load_policy(path, categories)


def test_cli_returns_nonzero_for_invalid_sources(tmp_path):
    (tmp_path / "ai.yaml").write_text("- {type: DOMAIN, value: '*.invalid'}\n")
    for script in ("validate.py", "build.py"):
        args = [sys.executable, str(ROOT / script), "--rules-dir", str(tmp_path)]
        if script == "build.py":
            args += ["--output", str(tmp_path / "output")]
        result = subprocess.run(args, capture_output=True, text=True)
        assert result.returncode == 1
        assert "非法域名" in result.stderr
    assert not (tmp_path / "output").exists()


def test_source_manifest_matches_captured_rules():
    categories, _ = load_sources()
    manifest = read_yaml(ROOT / "sources.yaml")
    assert len(manifest["commit"]) == 40
    assert manifest["license"] == "GPL-2.0"
    for source in manifest["sources"]:
        assert len(source["sha256"]) == 64
        selected_rules = {(r.type, r.value) for r in categories[source["category"]]}
        for selected in source["selected"]:
            rule_type, value, *_ = selected.split(",")
            assert (rule_type, normalize(rule_type, value)) in selected_rules
