import yaml

from tools import bump_upstream


def test_bump_updates_only_changed_commit_pins(tmp_path, monkeypatch):
    first = "a" * 40
    next_commit = "b" * 40
    path = tmp_path / "upstream.yaml"
    path.write_text(yaml.safe_dump({
        "version": 1,
        "repositories": {
            "one": {"repository": "example/one", "commit": first, "format": "classical"},
            "two": {"repository": "example/two", "commit": next_commit, "format": "v2ray"},
        },
        "sources": [],
    }, sort_keys=False))
    commits = {"example/one": "c" * 40, "example/two": next_commit}
    monkeypatch.setattr(bump_upstream, "latest_commit", lambda repository: commits[repository])

    assert bump_upstream.bump(path) == {"one": (first, "c" * 40)}
    result = yaml.safe_load(path.read_text())
    assert result["repositories"]["one"]["commit"] == "c" * 40
    assert result["repositories"]["two"]["commit"] == next_commit


def test_bump_leaves_file_untouched_when_pins_are_current(tmp_path, monkeypatch):
    sha = "a" * 40
    path = tmp_path / "upstream.yaml"
    original = "version: 1\nrepositories:\n  one:\n    repository: example/one\n    commit: " + sha + "\n    format: classical\nsources: []\n"
    path.write_text(original)
    monkeypatch.setattr(bump_upstream, "latest_commit", lambda _: sha)

    assert bump_upstream.bump(path) == {}
    assert path.read_text() == original
