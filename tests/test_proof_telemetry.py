"""Test the trace line lists in telemetry proof reports."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import proof_telemetry as pt


def test_a_list_can_mix_lines_and_ranges() -> None:
    assert pt.cited("trace.jsonl:15,17-20") == {15, 17, 18, 19, 20}


def test_a_list_accepts_spaces_and_both_range_marks() -> None:
    assert pt.cited("trace.jsonl:2-3, 5, 7\u20139, 12") == {2, 3, 5, 7, 8, 9, 12}


def test_a_cell_can_name_more_than_one_reference() -> None:
    assert pt.cited("trace.jsonl:3 and trace.jsonl:8-9") == {3, 8, 9}


def test_text_after_a_comma_ends_the_list() -> None:
    assert pt.cited("trace.jsonl:4, the refund") == {4}
    assert pt.cited("trace.jsonl:4,6-7, the refund 20") == {4, 6, 7}


def test_a_cell_with_no_trace_reference_gives_no_lines() -> None:
    assert pt.cited("The toy shop refunded order 20.") == set()
