"""The config key spec: the files of the app spec (SPEC.md sections 7.1, 7.2 and 9.2)."""

import hashlib
import json
from pathlib import Path

import pytest

from nookku import bridge, evaluation
from nookku.cli import main
from nookku.config import ConfigError, check, spec_files

CASES = sorted((Path(__file__).resolve().parent.parent / "conformance" / "spec").glob("*.json"))


def _project(tmp_path: Path, case: dict) -> tuple[Path, list]:
    """The project of a case, and its spec with <outside> filled in."""
    root, outside = tmp_path / "project", tmp_path / "outside"
    (root / ".nookku").mkdir(parents=True)
    outside.mkdir()
    for files, top in ((case.get("files", {}), root), (case.get("outside", {}), outside)):
        for name, text in files.items():
            (top / name).parent.mkdir(parents=True, exist_ok=True)
            (top / name).write_text(text)
    for name, target in case.get("links", {}).items():
        (root / name).symlink_to(target)
    spec = case["spec"]
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
        files = spec_files(root, spec)
    except ConfigError as e:
        assert str(e).replace(outside, "<outside>") == expect["error"]
        return
    assert "error" not in expect
    assert [str(f.relative_to(root.resolve())) for f in files] == expect["paths"]


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
    conf["spec"] = ["../APP_SPEC.md"]
    (tmp_path / ".nookku" / "config.json").write_text(json.dumps(conf))
    with pytest.raises(bridge.BridgeError, match="is not in the project folder"):
        bridge.load_config(tmp_path)


def test_the_prompt_names_each_spec_file_of_the_manifest(tmp_path: Path) -> None:
    folder = tmp_path / ".nookku" / "tests" / "t1"
    folder.mkdir(parents=True)
    spec = [{"path": "APP_SPEC.md", "sha256": "ab" * 32}]
    (folder / "manifest.json").write_text(json.dumps({"root": str(tmp_path), "spec": spec}))
    text = evaluation.prompt(folder)
    assert "The app spec of this test is in these files" in text
    assert f'- "APP_SPEC.md", SHA-256 {"ab" * 32}\n' in text
    assert "Read each spec file first" in text
    for manifest in ({"root": str(tmp_path), "spec": []}, {"root": str(tmp_path)}):
        (folder / "manifest.json").write_text(json.dumps(manifest))
        assert "app spec of this test" not in evaluation.prompt(folder)
