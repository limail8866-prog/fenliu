"""Exercise node discovery with the real Mihomo core, without live subscriptions."""

import json
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, build_opener

import pytest
import yaml

from build import clash_merge_config
from rulelib import Rule


@pytest.mark.skipif(not shutil.which("mihomo"), reason="Mihomo core is not installed")
@pytest.mark.parametrize("node_source", ["proxies", "proxy-providers", "both"])
def test_merge_discovers_active_subscription_nodes(tmp_path, node_source):
    # These deliberately unreachable loopback fixtures never provide proxy service.
    node = {"type": "http", "server": "127.0.0.1", "port": 9}
    base = {"proxy-groups": [{"name": "old-group", "type": "select", "proxies": ["DIRECT"]}],
            "rules": ["MATCH,old-group"]}
    expected = {"DIRECT"}
    if node_source in {"proxies", "both"}:
        base["proxies"] = [{"name": "inline-fixture", **node}]
        expected.add("inline-fixture")
    if node_source in {"proxy-providers", "both"}:
        provider_path = tmp_path / "nodes.yaml"
        provider_path.write_text(yaml.safe_dump({"proxies": [{"name": "provider-fixture", **node}]}))
        base["proxy-providers"] = {"existing-subscription": {"type": "file", "path": str(provider_path)}}
        expected.add("provider-fixture")
    policy = {
        "rule_base_url": "https://rules.invalid",
        "groups": [{"name": "节点选择", "type": "select", "proxies": ["DIRECT"], "use": ["subscription"]}],
        "category_order": ["sample"], "categories": {"sample": "节点选择"}, "final": "节点选择",
    }
    overlay = clash_merge_config(policy, {"sample": [Rule("DOMAIN", "example.invalid")]})
    # Verge replaces sequences and retains fields absent from the overlay.
    merged = {**base, **overlay}
    # Isolate routing/group integration from GEO downloads and DNS availability.
    merged["dns"] = {"enable": False}
    merged["rules"].remove("GEOIP,CN,DIRECT")
    for provider in merged["rule-providers"].values():
        provider.clear()
        provider.update(type="inline", behavior="domain", payload=["example.invalid"])
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    merged["external-controller"] = f"127.0.0.1:{port}"
    config_path = tmp_path / "merged.yaml"
    config_path.write_text(yaml.safe_dump(merged, allow_unicode=True))
    endpoint = f"http://127.0.0.1:{port}/proxies/{quote('节点选择')}"
    opener = build_opener(ProxyHandler({}))
    with (tmp_path / "mihomo.log").open("w+") as log:
        process = subprocess.Popen(
            [shutil.which("mihomo"), "-d", str(tmp_path), "-f", str(config_path)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline and process.poll() is None:
                try:
                    with opener.open(endpoint, timeout=1) as response:
                        group = json.load(response)
                    if set(group["all"]) == expected:
                        assert group["type"] == "Selector"
                        return
                except (URLError, TimeoutError):
                    pass
                time.sleep(0.1)
            log.seek(0)
            pytest.fail(f"Mihomo did not discover {expected}:\n{log.read()}")
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
