import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("stealth", ROOT / "scripts" / "stealth.py")
assert spec and spec.loader
stealth = importlib.util.module_from_spec(spec)
sys.modules["stealth"] = stealth
spec.loader.exec_module(stealth)


def test_a_phrase_matches_across_case_and_punctuation():
    hashes = {stealth.digest("toy shop")}
    items = [("a.md", "line one\nWe run a Toy-Shop agent.\n"), ("b.md", "toys, shopping")]
    assert stealth.hits(items, hashes) == ["a.md:2"]


def test_a_term_longer_than_the_limit_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", ["one two three four\n"])
    assert stealth.main(["add"]) == 2


def test_the_repo_has_no_banned_term():
    assert stealth.banned(), "the hash list is empty, so the gate checks nothing"
    assert stealth.hits(stealth.sources(), stealth.banned()) == []
