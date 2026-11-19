# Evaluation dashboard

This example is a dashboard of the runs and the gate runs of a project. It is static files. It reads only the read-only API of `nookku dashboard` ([docs/reference/api.md](../../docs/reference/api.md)), and it shows the data with the components of the mugham kit.

The kit is a build-time choice. The Python package of Nookku has no dependency on it. The build copies the pinned files of the kit next to the site.

## Build and serve

1. Build the site into a new folder. The build clones the tag of the pin with git:

   ```bash
   python examples/evaluation-dashboard/build.py --out dashboard-site
   ```

2. Serve the site and the API of your project:

   ```bash
   nookku dashboard --site dashboard-site
   ```

3. Open the `open` address that the command prints, for example `http://127.0.0.1:8765/#token=...`. The token is new each time the server starts, and each API request must send it.

The page lists the gate runs and the runs. Each gate run shows its aggregate verdict, its subject digest and the state of its seal. "Open" on a gate run shows the verdict of each test. Each run shows its verdict, its counts and the state of its seal. "Open" on a run shows its findings and the report of its evaluation. A run with a broken seal shows `broken`, and its verdict shows `cannot be used`.

## The pin of the kit

[mugham.json](mugham.json) gives the repository, the tag `v0.4.0`, the commit and the copied paths of the kit. [checksums.json](checksums.json) gives the SHA-256 of each copied file. The build stops and writes no output folder if:

- the tag does not point to the pinned commit;
- the checkout is not at the pinned commit;
- a file is missing, extra or changed.

To change the pin, change `tag` and `commit` in `mugham.json`, then write the checksums again from a checkout at the new tag. Review the diff of `checksums.json` and of `docs/PROVENANCE.md`:

```bash
python examples/evaluation-dashboard/build.py --checksums --mugham <checkout>
```

## The check

[run.py](run.py) is the check of the CI job `dashboard`. It makes a toy shop project with a gate run of 2 scripted tests, 2 replays and 1 broken seal. It builds the site, starts `nookku dashboard` on a free port, and checks the API. Then it runs Chrome with no window on [test/harness.html](test/harness.html). The harness loads the dashboard at 360 px and at 1280 px, compares the page with the API, and opens a run and a gate run. The check needs no model.

```bash
uv run python examples/evaluation-dashboard/run.py --out dashboard.json
```

Give `--mugham <checkout>` to use a local checkout of the kit at the pin. Set `CHROME` to the path of Chrome or Chromium if it is not on the PATH.
