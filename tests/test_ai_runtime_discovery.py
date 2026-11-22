import os
from pathlib import Path

import pytest

from roosta import ai_runtime


@pytest.fixture
def discovery(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(ai_runtime, "RUNTIME_ROOT", tmp_path / "managed")
    shim = tmp_path / ".cmuxterm/cmux-cli-shims/session/claude"
    direct = tmp_path / "bin/claude"
    local = tmp_path / ".local/bin/claude"
    managed = ai_runtime.binary_path(ai_runtime.RUNTIME_ROOT, "claude", "1.0.0")
    monkeypatch.setenv("PATH", os.pathsep.join(map(str, (shim.parent, direct.parent))))
    for binary in (shim, direct, local, managed):
        binary.parent.mkdir(parents=True)
    shim.touch(mode=0o755)

    def probe(binary):
        path = Path(binary)
        if not path.is_file():
            return ""
        # Only explicitly versioned test binaries may reach the probe.
        return versions[path]

    versions = {}
    monkeypatch.setattr(ai_runtime, "version", probe)
    return direct, local, managed, versions


@pytest.mark.parametrize(("direct_version", "local_version", "managed_version", "winner"), [
    ("2.0.0", "2.0.0", "2.0.0", "direct"),
    ("1.0.0", "2.0.0", "2.0.0", "local"),
    ("1.0.0", "2.0.0", "10.0.0", "managed"),
])
def test_skips_first_path_shim_before_comparing_versions(
        discovery, direct_version, local_version, managed_version, winner):
    direct, local, managed, versions = discovery
    versions.update({direct: direct_version, local: local_version, managed: managed_version})
    for path in versions:
        path.touch(mode=0o755)
    assert ai_runtime.find("claude") == str({"direct": direct, "local": local, "managed": managed}[winner])


@pytest.mark.parametrize("target", [
    "cmux.app/Contents/Resources/bin/cmux-claude-wrapper",
    "cmux.app/Contents/Resources/bin/claude",
    "cmux-cli-shims/other-session/claude",
])
def test_wrapper_aliases_are_never_probed(discovery, tmp_path, target):
    direct, local, managed, versions = discovery
    wrapper = tmp_path / target
    wrapper.parent.mkdir(parents=True)
    wrapper.touch(mode=0o755)
    direct.symlink_to(wrapper)
    local.symlink_to(wrapper)
    assert ai_runtime.find("claude") == ""
    managed.touch(mode=0o755)
    versions[managed] = "1.0.0"
    assert ai_runtime.find("claude") == str(managed)


@pytest.mark.parametrize("target", [
    ".local/share/claude/versions/2.0.0",
    "custom-cmux-cli-shims/bin/claude",
    "Other.app/Contents/Resources/bin/claude",
])
def test_local_symlink_to_user_install_is_preserved(discovery, tmp_path, target):
    _, local, _, versions = discovery
    binary = tmp_path / target
    binary.parent.mkdir(parents=True)
    binary.touch(mode=0o755)
    local.symlink_to(binary)
    versions[local] = "2.0.0"
    assert ai_runtime.find("claude") == str(local)


def test_only_shim_and_looping_local_link(discovery):
    _, local, _, _ = discovery
    local.symlink_to(local)
    assert ai_runtime.find("claude") == ""
