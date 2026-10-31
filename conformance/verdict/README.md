# Verdict cases

Each folder is one case of the verdict (SPEC.md section 7.14). `case.json` gives the app spec files (`files`, as path and text), or a manifest (`manifest`), and the `counts` of `findings.json`, or `null` for no `findings.json`. `expect_verdict.json` is the expected `verdict.json`. I wrote each expected file by hand. `tests/test_verdict.py` reads the limits of the spec files into the manifest, writes `findings.json`, builds `verdict.json`, and compares the 2 files.

| Case | It shows |
|---|---|
| `toy_shop_pass` | The toy shop limits: 0 `agent_error` and at most 1 `repeated_reply`. 1 `repeated_reply` is at the limit, so it passes. A class with no limit passes with any count. |
| `toy_shop_fail` | The same limits with 1 `agent_error` and 2 `repeated_reply`. Both classes fail, so the verdict is `fail`. |
| `bad_rows` | Rows that are not limits: an unknown class, a second row for one class, a row with no `Finding`, a different count of cells, and a `Most` that is negative, not whole or longer than 9 digits. Each one is a problem, so the verdict is `fail`. |
| `section_with_no_table` | A `Verdict` section with no table is a problem. |
| `two_files_extra_column` | Limits in 2 files, with a heading of level 3 in lowercase, the columns in another order, a third column and rows with no `\|` at the end. |
| `no_section` | A spec with no `Verdict` section has no limits, so the verdict is `pass`. |
| `no_findings` | No `findings.json`: each count is `null`, each class with a limit fails, and the problem names the file. |
| `test_before_the_key` | A manifest with no key `verdict`, from Nookku 0.5.6 or earlier, has no limits. |
