"""The seam test of the release samples of Koodam (#578).

The CI job `release-samples` runs this script. It needs no cluster and no model. Each Koodam
release has sample files that its release workflow made from a kind run of the tagged commit
(koodam#331). The script runs the readers of Nookku on the samples of the pinned tag, so a reader
is tested on lines that the platform wrote, not only on lines that a person wrote.

The checks:

S1  Each sample file has the SHA-256 of the pin.
S2  The span reader (SPEC.md section 8.8) reads egress-spans.jsonl: the file has 1 span or more,
    and no line is invalid. A span with a contract version that this nookku does not read stops
    the script with the message of the reader.
S3  The gateway reader (SPEC.md section 8.9) reads gateway-log.jsonl: each line is a log with a
    start time and a key alias, and 1 log or more is a model call that the reader knows.
S4  The ingress span reader (SPEC.md section 8.12) reads app-ingress-spans.jsonl: the file has 1
    span or more, and no line is invalid. A span with a format version that this nookku does not
    read stops the script with the message of the reader.

The script writes the result to OUT (default proofs/release-samples/results.json). The result has
the tag, and the SHA-256 and the size of each sample file.

usage: python scripts/release_samples.py [--dir FOLDER] [--out PATH]

With --dir, the script reads the sample files from FOLDER and makes no download.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

from nookku import __version__, egress_spans, gateway, ingress_spans
from nookku.record import RecordError

ROOT = Path(__file__).resolve().parent.parent

# The pinned Koodam tag (docs/getting-started-cluster.md#the-koodam-tag-of-the-release-samples).
# Use only a tag of a Koodam release.
KOODAM_TAG = "v0.4.0"
# The commit of the tag. The result records it. The SHA-256 values below pin the bytes.
KOODAM_COMMIT = "1a8c3a133c4155e1120268109e7436d07cbcb095"
SPANS, LOGS, INGRESS = "egress-spans.jsonl", "gateway-log.jsonl", "app-ingress-spans.jsonl"
# The SHA-256 of each sample file of the pinned tag, from `checksums.txt` of the release.
SAMPLES = {
    SPANS: "016cac2cdb7468973cc275c8efe1fce80e73feca46b7c35fcb7470415a1e7a63",
    LOGS: "191ba84384df90e41bcaafd07d07bc737ea75bcc565311253e9d7362e0db0f8b",
    INGRESS: "1282eb24a1010ceddadd445e838964b1c131653297d73c6daf7a07d2c62bed80",
}
ASSET = "https://github.com/mohanraj00/koodam/releases/download/{tag}/{name}"
# The most bytes of a sample file that the script reads. This is a chosen value.
READ_LIMIT = 64 * 1024 * 1024
TIMEOUT = 60.0
SHA256 = re.compile(r"[0-9a-f]{64}")


class Stop(Exception):
    """A check failed. The message says which one, and why."""


def download(tag: str, name: str) -> bytes:
    """The bytes of a sample file of a release."""
    url = ASSET.format(tag=tag, name=name)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as response:
            data: bytes = response.read(READ_LIMIT + 1)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise Stop(f"{name}: cannot download {url}: {e}") from None
    if len(data) > READ_LIMIT:
        raise Stop(f"{name}: the file has more than {READ_LIMIT} bytes.")
    return data


def spans(tag: str, data: bytes) -> dict[str, Any]:
    """S2: the counts of the span reader for the span sample."""
    try:
        kept, counts = egress_spans.parse(data, Path(SPANS), None, None, [])
    except RecordError as e:
        raise Stop(
            f"S2: the span reader cannot read the sample of the release {tag}. {e}"
        ) from None
    ignored = counts["ignored"]
    bad = {k: n for k, n in ignored.items() if k in ("invalid", "invalid_json")}
    if bad:
        raise Stop(f"S2: {SPANS} of the release {tag} has lines that the reader refuses: {bad}.")
    if not kept:
        raise Stop(f"S2: {SPANS} of the release {tag} has no span that the reader keeps.")
    versions = Counter(str(s["span"].get("v", egress_spans.VERSIONS[0])) for s in kept)
    return {
        "rows": counts["rows"],
        "spans": counts["spans"],
        "ignored": ignored,
        "versions": dict(sorted(versions.items())),
        "hosts": len(counts["hosts"]),
    }


def logs(tag: str, data: bytes) -> dict[str, Any]:
    """S3: the counts of the gateway reader for the log sample."""
    try:
        found = gateway.logs(data)
    except gateway.GatewayError as e:
        raise Stop(
            f"S3: the gateway reader cannot read the sample of the release {tag}. {e}"
        ) from None
    types: Counter[str] = Counter()
    calls = 0
    for n, log in enumerate(found, 1):
        if not isinstance(log, dict):
            raise Stop(f"S3: log {n} of {LOGS} of the release {tag} is not an object.")
        row = gateway.call_row(log)
        if row["started"] is None or not isinstance(row["key_alias"], str):
            raise Stop(
                f"S3: log {n} of {LOGS} of the release {tag} has no start time or no key alias."
            )
        types[row["call_type"]] += 1
        calls += row["api"] is not None
    if not calls:
        raise Stop(f"S3: {LOGS} of the release {tag} has no model call that the reader knows.")
    return {"logs": len(found), "model_calls": calls, "call_types": dict(sorted(types.items()))}


def ingress(tag: str, data: bytes) -> dict[str, Any]:
    """S4: the counts of the ingress span reader for the App ingress span sample."""
    try:
        counts = ingress_spans.parse(data, Path(INGRESS), None, None, lambda ts: None, 0)
    except RecordError as e:
        raise Stop(
            f"S4: the ingress span reader cannot read the sample of the release {tag}. {e}"
        ) from None
    ignored = counts["ignored"]
    bad = {k: n for k, n in ignored.items() if k in ("invalid", "invalid_json")}
    if bad:
        raise Stop(f"S4: {INGRESS} of the release {tag} has lines that the reader refuses: {bad}.")
    if not counts["spans"]:
        raise Stop(f"S4: {INGRESS} of the release {tag} has no span that the reader keeps.")
    return {
        "rows": counts["rows"],
        "spans": counts["spans"],
        "ignored": ignored,
        "outcomes": counts["outcomes"],
    }


def check(tag: str, pins: dict[str, str], fetch: Callable[[str], bytes]) -> dict[str, Any]:
    """The result of the checks S1 to S4 for the samples of the release `tag`. `pins` has the
    SHA-256 of each sample file, and `fetch` gives the bytes of a sample file."""
    if (
        not tag
        or sorted(pins) != sorted(SAMPLES)
        or not all(SHA256.fullmatch(v) for v in pins.values())
    ):
        raise Stop("No release is pinned. Set KOODAM_TAG and the SHA-256 of each file in SAMPLES.")
    files: dict[str, Any] = {}
    data: dict[str, bytes] = {}
    for name in sorted(pins):
        data[name] = fetch(name)
        digest = hashlib.sha256(data[name]).hexdigest()
        if digest != pins[name]:
            raise Stop(
                f"S1: {name} of the release {tag} has the SHA-256 {digest}. The pin has "
                f"{pins[name]}. A release does not change its files, so do not change the pin "
                "to make this check pass."
            )
        files[name] = {"sha256": digest, "bytes": len(data[name])}
    return {
        "proof": "release-samples",
        "koodam": tag,
        "nookku": __version__,
        "contract_versions": list(egress_spans.VERSIONS),
        "ingress_versions": list(ingress_spans.VERSIONS),
        "files": files,
        "spans": spans(tag, data[SPANS]),
        "gateway": logs(tag, data[LOGS]),
        "ingress": ingress(tag, data[INGRESS]),
        "pass": True,
    }


def _local(folder: Path) -> Callable[[str], bytes]:
    def fetch(name: str) -> bytes:
        try:
            return (folder / name).read_bytes()
        except OSError as e:
            raise Stop(f"{name}: cannot read it in {folder}: {e.strerror}") from None

    return fetch


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--dir", type=Path, help="read the sample files from this folder")
    ap.add_argument(
        "--out", type=Path, default=ROOT / "proofs" / "release-samples" / "results.json"
    )
    args = ap.parse_args(argv)
    fetch = _local(args.dir) if args.dir else lambda name: download(KOODAM_TAG, name)
    try:
        result = check(KOODAM_TAG, SAMPLES, fetch)
    except Stop as e:
        print(f"release samples: {e}", file=sys.stderr)
        return 1
    result = {"proof": result.pop("proof"), "koodam_commit": KOODAM_COMMIT, **result}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
