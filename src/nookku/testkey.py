"""The gateway key of a Koodam TestKey (SPEC.md section 7.16).

Koodam can give one test in a Workspace its own gateway key. The Workspace pod then has the
folder /etc/koodam/test-gateway/ with the files `key`, `alias`, `base-url` and `model`. The bridge
reads them at the start of a test. The key goes only to the entry, in the key variable of each model
API. The manifest records the alias, the base URL and the model, never the key.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import is_http_url

FOLDER = Path("/etc/koodam/test-gateway")
# The variable that gives another folder, for example for a test of Nookku itself.
DIR_ENV = "NOOKKU_TEST_KEY_DIR"
FILES = ("key", "alias", "base-url", "model")
# A chosen limit for each file. A Koodam key, alias, URL or model name is much shorter.
LIMIT = 4096
# The alias of Koodam: tk-<testID cut to 48 characters>-<first 8 characters of the TestKey UID>.
ALIAS = re.compile(r"tk-[A-Za-z0-9][A-Za-z0-9_-]{0,47}-[0-9a-f]{8}")
# The key goes into an HTTP header, so it has only visible ASCII characters.
KEY = re.compile(r"[\x21-\x7e]+")
# The key variable of the SDK of each model API (SPEC.md section 7.7).
KEY_ENV = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}
# The variable that gives the entry the model of the gateway.
MODEL_ENV = "NOOKKU_TEST_KEY_MODEL"


class GatewayKeyError(Exception):
    """The folder has a key that cannot be used. The text never holds the key."""


@dataclass(frozen=True)
class GatewayKey:
    key: str = field(repr=False)
    alias: str
    base_url: str
    model: str

    def record(self) -> dict[str, Any]:
        """The manifest value: no key."""
        return {"alias": self.alias, "base_url": self.base_url, "model": self.model}

    def environment(self, apis: list[str]) -> dict[str, str]:
        """The variables of the entry for the model APIs `apis`: the key in the key variable of
        each API, and the model. No model API gives no variable, so the key goes nowhere."""
        if not apis:
            return {}
        return {**{KEY_ENV[a]: self.key for a in apis}, MODEL_ENV: self.model}


def folder(environ: Mapping[str, str]) -> Path:
    """The folder of the key: the value of DIR_ENV, else the folder of Koodam."""
    return Path(environ[DIR_ENV]) if environ.get(DIR_ENV) else FOLDER


def _text(folder: Path, name: str) -> str:
    try:
        with (folder / name).open("rb") as f:
            data = f.read(LIMIT + 1)
    except OSError as e:
        raise GatewayKeyError(f"cannot read the file {name}: {e.strerror}") from None
    if len(data) > LIMIT:
        raise GatewayKeyError(f"the file {name} has more than {LIMIT} bytes")
    try:
        return data.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise GatewayKeyError(f"the file {name} is not UTF-8") from None


def read(folder: Path = FOLDER) -> GatewayKey | None:
    """The key of the folder, or None if the folder does not exist or has none of the 4 files.

    Koodam mounts the folder as optional, so a pod with no TestKey can have an empty folder.
    Raise GatewayKeyError if the folder has only some of the files, or a value that is not valid."""
    if not folder.is_dir():
        return None
    there = [n for n in FILES if (folder / n).exists()]
    if not there:
        return None
    missing = [n for n in FILES if n not in there]
    if missing:
        raise GatewayKeyError(f"{folder} has no file {', '.join(missing)}")
    key, alias, base_url, model = (_text(folder, n) for n in FILES)
    if not KEY.fullmatch(key):
        raise GatewayKeyError("the file key is empty or has a character that is not visible ASCII")
    if not ALIAS.fullmatch(alias):
        raise GatewayKeyError(f"the alias {alias!r} does not have the form tk-<test id>-<uid8>")
    if not is_http_url(base_url) or any(c.isspace() for c in base_url):
        raise GatewayKeyError(f"the base URL {base_url!r} is not an http or https URL")
    if not model or not model.isprintable():
        raise GatewayKeyError("the file model is empty or has a character that is not printable")
    return GatewayKey(key, alias, base_url.rstrip("/"), model)
