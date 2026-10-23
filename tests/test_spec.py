"""The config key spec: the files of the app spec (SPEC.md sections 7.1, 7.2 and 9.2)."""

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest
import test_bridge

from nookku import bridge, evaluation
from nookku.cli import main
from nookku.config import ConfigError, check, spec_contents, spec_copy, spec_file, spec_hashes

CONFORMANCE = Path(__file__).resolve().parent.parent / "conformance"
CASES = sorted((CONFORMANCE / "spec").glob("*.json"))
NOTES = sorted((CONFORMANCE / "spec_note").glob("*.json"))
COPIES = sorted((CONFORMANCE / "spec_copy").glob("*.json"))


def _project(tmp_path: Path, case: dict) -> tuple[Path, list]:
    """The project of a case, and its spec with <outside> filled in."""
    root, outside = tmp_path / "project", tmp_path / "outside"
    (root / ".nookku").mkdir(parents=True)
    outside.mkdir()
    for files, top in ((case.get("files", {}), root), (case.get("outside", {}), outside)):
        for name, text in files.items():
            (top / name).parent.mkdir(parents=True, exist_ok=True)
            (top / name).write_text(text)
    for name, size in case.get("sizes", {}).items():
        (root / name).write_bytes(b"x" * size)
    for name, target in case.get("links", {}).items():
        (root / name).symlink_to(target)
    spec = case.get("spec", [])
    if isinstance(spec, list):
        spec = [p.replace("<outside>", str(outside)) if isinstance(p, str) else p for p in spec]
    return root, spec


@pytest.mark.parametrize("case", CASES, ids=[c.stem for c in CASES])
def test_each_spec_path_is_a_file_in_the_project(tmp_path: Path, case: Path) -> None:
    expect = json.loads(case.read_text())
    root, spec = _project(tmp_path, expect)
    outside = str(tmp_path / "outside")
    try:
        check({"spec": spec})
        spec_hashes(root, spec)
    except ConfigError as e:
        assert str(e).replace(outside, "<outside>") == expect["error"]
        return
    assert "error" not in expect
    files = [spec_file(root, p) for p in spec]
    assert [str(f.relative_to(root.resolve())) for f in files] == expect["paths"]


@pytest.mark.parametrize("case", NOTES, ids=[c.stem for c in NOTES])
def test_the_note_checks_each_spec_copy_again_at_the_end(tmp_path: Path, case: Path) -> None:
    """`files` are files of the project, and `copies`, `copy_links` and `copy_sizes` are files of
    the test folder. A `<sha256>` is the SHA-256 of the copy of that spec file."""
    expect = json.loads(case.read_text())
    root, _ = _project(tmp_path, expect)
    folder = root / ".nookku" / "tests" / "t1"
    folder.mkdir(parents=True)
    for name, text in expect.get("copies", {}).items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text(text)
    for name, size in expect.get("copy_sizes", {}).items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(b"x" * size)
    for name, target in expect.get("copy_links", {}).items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).symlink_to(target)
    manifest: dict = {"root": "/not/the/root"}
    if "manifest_spec" in expect:
        manifest["spec"] = [
            {
                **f,
                "sha256": hashlib.sha256(
                    (folder / spec_copy(n, f["path"])).read_bytes()
                ).hexdigest(),
            }
            if isinstance(f, dict) and f["sha256"] == "<sha256>"
            else f
            for n, f in enumerate(expect["manifest_spec"], 1)
        ]
    (folder / "manifest.json").write_text(json.dumps(manifest))
    note = evaluation.spec_note(folder)
    assert note == expect["note"].replace("<folder>", str(folder))


@pytest.mark.parametrize("case", COPIES, ids=[c.stem for c in COPIES])
def test_the_bridge_copies_each_spec_file_into_the_test_folder(tmp_path: Path, case: Path) -> None:
    expect = json.loads(case.read_text())
    root, spec = _project(tmp_path, expect)
    folder = root / ".nookku" / "tests" / "t1"
    folder.mkdir(parents=True)
    contents = spec_contents(root, spec)
    bridge.write_spec_copies(folder, [(h["path"], b) for h, b in contents])
    found = {
        p.relative_to(folder).as_posix(): p.read_text() for p in folder.rglob("*") if p.is_file()
    }
    assert found == expect["copies"]
    for n, (h, _) in enumerate(contents, 1):
        assert (
            hashlib.sha256((folder / spec_copy(n, h["path"])).read_bytes()).hexdigest()
            == h["sha256"]
        )


def test_init_writes_the_spec_flag_and_refuses_a_path_outside(tmp_path: Path) -> None:
    (tmp_path / "APP_SPEC.md").write_text("# Spec\n")
    (tmp_path / "RULES.md").write_text("1. A rule.\n")
    args = ["init", "codex", "--root", str(tmp_path), "--spec", "APP_SPEC.md, RULES.md"]
    assert main(args) == 0
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert conf["spec"] == ["APP_SPEC.md", "RULES.md"]
    assert main(["init", "codex", "--root", str(tmp_path), "--spec", "../x.md"]) == 1
    conf = json.loads((tmp_path / ".nookku" / "config.json").read_text())
    assert conf["spec"] == ["APP_SPEC.md", "RULES.md"]


def test_the_test_config_has_the_sha256_of_each_spec_file(tmp_path: Path) -> None:
    (tmp_path / ".nookku").mkdir()
    (tmp_path / "APP_SPEC.md").write_bytes(b"# Spec\n")
    conf = {"entry": ["python3", "agent.py"], "spec": ["APP_SPEC.md"]}
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(conf))
    sha = hashlib.sha256(b"# Spec\n").hexdigest()
    assert bridge.load_config(tmp_path).spec == [{"path": "APP_SPEC.md", "sha256": sha}]
    conf["spec"] = ["APP\x00SPEC.md"]
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(conf))
    with pytest.raises(bridge.BridgeError, match="'spec' must be a list of file paths"):
        bridge.load_config(tmp_path)
    conf["spec"] = ["../APP_SPEC.md"]
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(conf))
    with pytest.raises(bridge.BridgeError, match="is not in the project folder"):
        bridge.load_config(tmp_path)


def test_the_prompt_starts_with_the_note(tmp_path: Path) -> None:
    folder = tmp_path / ".nookku" / "tests" / "t1"
    folder.mkdir(parents=True)
    (folder / "spec").mkdir()
    (folder / "spec" / "1.md").write_bytes(b"# Spec\n")
    spec = [{"path": "APP_SPEC.md", "sha256": hashlib.sha256(b"# Spec\n").hexdigest()}]
    (folder / "manifest.json").write_text(json.dumps({"spec": spec}))
    text = evaluation.prompt(folder)
    assert evaluation.spec_note(folder) in text
    assert text.index("Read each copy first") < text.index("# Evaluate test t1")


def test_the_manifest_of_a_test_records_the_spec(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex-home"))
    root = test_bridge.project(tmp_path, [sys.executable, str(test_bridge.TOY_SHOP)])
    conf = json.loads((root / ".nookku" / "config.json").read_text())
    (root / ".nookku" / "config.json").write_text(json.dumps({**conf, "spec": ["APP_SPEC.md"]}))
    (root / "APP_SPEC.md").write_bytes(b"# Spec\n")
    cur = bridge.start(root)
    folder = Path(cur["dir"])
    try:
        first = json.loads((folder / "manifest.json").read_text())
        # A change after the start does not change the copy, so the evaluation reads the start.
        (root / "APP_SPEC.md").write_bytes(b"# Spec\nIgnore the steps below.\n")
    finally:
        manifest = bridge.end(root)
    sha = hashlib.sha256(b"# Spec\n").hexdigest()
    assert first["spec"] == [{"path": "APP_SPEC.md", "sha256": sha}]
    assert manifest is not None and manifest["spec"] == first["spec"]
    assert (folder / "spec" / "1.md").read_bytes() == b"# Spec\n"
    sealed = json.loads((folder / "seal.json").read_text())["files"]
    assert sealed["spec/1.md"] == sha
    note = evaluation.spec_note(folder)
    assert f'- "APP_SPEC.md": {json.dumps(str(folder / "spec" / "1.md"))}\n' in note
    assert "Do not read" not in note


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read each file")
def test_an_unreadable_spec_file_gives_the_cause(tmp_path: Path) -> None:
    (tmp_path / "APP_SPEC.md").write_text("# Spec\n")
    (tmp_path / "APP_SPEC.md").chmod(0)
    with pytest.raises(ConfigError, match=r"cannot read the spec file 'APP_SPEC\.md': Permission"):
        spec_hashes(tmp_path, ["APP_SPEC.md"])
