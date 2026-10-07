"""The parts of examples/toy-shop-full/ that need no model: the stock service, the toy note model
and the calls of the app to them."""

import json
import shutil
import sys
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

FULL = Path(__file__).resolve().parent.parent / "examples" / "toy-shop-full"
sys.path.insert(0, str(FULL))

import services  # noqa: E402
import stock  # noqa: E402
import toy_model  # noqa: E402


@pytest.fixture
def stock_service(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    state = tmp_path / "stock.json"
    shutil.copy(FULL / "stock.json", state)
    server = stock.StockService(0, state)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("STOCK_URL", server.url)
    yield state
    server.shutdown()
    server.server_close()


def test_stock_and_a_missing_item(stock_service: Path) -> None:
    assert services.stock("teapot-set") == {"sku": "teapot-set", "left": 3}
    assert services.stock("toy train") == {"error": "no such item: toy train"}


def test_the_planted_bug_reserves_twice(stock_service: Path) -> None:
    # The app asks for 1 teapot set. Its retry loop has no break, so the service reserves 2.
    done = services.reserve("6210", "teapot-set", 1)
    assert done["qty"] == 1 and done["left"] == 1
    item = json.loads(stock_service.read_text())["teapot-set"]
    assert item["left"] == 1 and len(item["reservations"]) == 2


def test_no_stock_gives_an_error(stock_service: Path) -> None:
    assert services.reserve("6210", "teapot-set", 9) == {"error": "not enough stock"}


def test_the_case_note_comes_from_the_toy_model_as_a_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = toy_model.ToyModel(0)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    monkeypatch.setenv("OPENAI_BASE_URL", model.url)
    try:
        note = services.case_note("Can I reserve a teapot set?\nThanks.", "Yes, I reserved 1.")
    finally:
        model.shutdown()
        model.server_close()
    assert note == "Case note: Can I reserve a teapot set?"
