import hashlib

import pytest

from rulelib import Rule, SourceError
from tools.sync_rules import collect_sources, parse_line, prepare_import


@pytest.mark.parametrize("line,format_name,expected", [
    ("DOMAIN-SUFFIX,EXAMPLE.COM", "classical", ("DOMAIN-SUFFIX", "example.com")),
    ("IP-CIDR6,2001:db8::/32,no-resolve", "classical", ("IP-CIDR6", "2001:db8::/32")),
    ("example.com @cn", "v2ray", ("DOMAIN-SUFFIX", "example.com")),
    ("full:api.example.com # exact", "v2ray", ("DOMAIN", "api.example.com")),
    ("keyword:example", "v2ray", ("DOMAIN-KEYWORD", "example")),
])
def test_upstream_formats(line, format_name, expected):
    assert parse_line(line, format_name) == expected


@pytest.mark.parametrize("line,reason", [
    ("IP-ASN,1234", "unsupported-type"),
    ("PROCESS-NAME,example.exe", "unsupported-type"),
    ("DOMAIN,example.com,unexpected", "unsupported-option"),
    ("DOMAIN-SUFFIX,*.example.com", "invalid-value"),
    ("GEOIP,CN", "generated-geoip-cn-tail"),
])
def test_unsupported_rules_are_explicit(line, reason):
    with pytest.raises(SourceError, match=reason):
        parse_line(line, "classical")


def test_import_deduplicates_by_priority_keeps_manual_rules_and_resolves_includes(monkeypatch):
    snapshots = {"data/root": b"include:child\nfull:api.example.com\nregexp:unsupported\n",
                 "data/child": b"example.com\n",
                 "lower.list": b"DOMAIN,api.example.com\nDOMAIN-SUFFIX,other.com\n"}
    monkeypatch.setattr("tools.sync_rules.fetch_snapshot", lambda repo, path, *args: snapshots[path])
    spec = {"repositories": {"v2fly": {"format": "v2ray", "repository": "example/domains", "commit": "a" * 40},
                             "blackmatrix": {"format": "classical", "repository": "example/rules", "commit": "b" * 40}},
            "sources": [{"repository": "v2fly", "path": "data/root", "category": "ai"},
                        {"repository": "blackmatrix", "path": "lower.list", "category": "global_proxy"}]}
    existing = {"ai": [Rule("DOMAIN", "manual.example.net", "my custom rule"),
                       Rule("DOMAIN", "removed.example.net", "upstream:v2fly:data/root")]}
    categories, manifest = prepare_import(spec, existing, ["ai", "global_proxy"], None, True)
    assert categories["ai"][0] == existing["ai"][0]
    assert {rule.value for rule in categories["ai"]} == {"manual.example.net", "api.example.com", "example.com"}
    assert [rule.value for rule in categories["global_proxy"]] == ["other.com"]
    assert any(source["skipped"].get("unsupported-type") == 1 for source in manifest["sources"])
    assert any(source["skipped"].get("owned-by-higher-category") == 1 for source in manifest["sources"])
    expected = {("example/domains", "a" * 40, "data/root"): "0" * 64}
    with pytest.raises(SourceError, match="摘要变化"):
        collect_sources(spec, None, True, expected)


def test_failed_download_cannot_produce_partial_import(monkeypatch):
    def fail(*args):
        raise OSError("download failed")
    monkeypatch.setattr("tools.sync_rules.fetch_snapshot", fail)
    spec = {"repositories": {"source": {"format": "classical"}},
            "sources": [{"repository": "source", "category": "ai", "path": "test.list"}]}
    with pytest.raises(OSError, match="download failed"):
        prepare_import(spec, {}, ["ai"], None, False)
