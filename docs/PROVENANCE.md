# Provenance

This page lists the code from other projects that a part of this repo uses, and how the repo pins it. The Python package of Nookku has no such code.

## The mugham kit

| Field | Value |
|---|---|
| Used by | [examples/evaluation-dashboard/](../examples/evaluation-dashboard/), at build time only |
| Repository | https://github.com/mohanraj00/mugham |
| Tag | `v0.4.0` |
| Commit | `715ce6b8db044d9acebc2a35f6a64e48582152ea` |
| Paths | `src`, `catalog`, `LICENSE` |
| License | Apache-2.0 ([licenses/THIRD_PARTY.md](../licenses/THIRD_PARTY.md)) |
| Pin | [mugham.json](../examples/evaluation-dashboard/mugham.json) |
| Checksums | [checksums.json](../examples/evaluation-dashboard/checksums.json), the SHA-256 of each of the 89 copied files |

The repo does not hold a copy of the kit. [build.py](../examples/evaluation-dashboard/build.py) clones the tag, checks that the tag and the checkout are at the pinned commit, and checks each file against the checksums. Then it copies the files into the output folder, under `mugham/`. The output folder holds the `LICENSE` file of the kit.

A change of the pin changes `mugham.json`, `checksums.json` and this page in the same PR.
