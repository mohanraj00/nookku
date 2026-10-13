"""config.has_entry reads config.json with the config reader (#295)."""

from __future__ import annotations

from pathlib import Path

import pytest

from nookku.config import FILE, has_entry

CASES = [
    ('{"entry": ["python3", "shop.py"]}', True),
    # An entry and an error: the file still has an entry, so that start shows the error.
    ('{"entry": ["python3", "shop.py"], "unknown_key": 1}', True),
    ('{"entry": []}', False),
    ('{"entry": "python3 shop.py"}', False),
    ("{}", False),
    ('["entry"]', False),
    ("not json", False),
]


@pytest.mark.parametrize(("text", "expected"), CASES)
def test_has_entry(tmp_path: Path, text: str, expected: bool) -> None:
    path = tmp_path / FILE
    path.parent.mkdir()
    path.write_text(text, encoding="utf-8")
    assert has_entry(tmp_path) is expected


def test_no_file_has_no_entry(tmp_path: Path) -> None:
    assert has_entry(tmp_path) is False
