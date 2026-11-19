# Verdict cases

Each folder is one case of the verdict (SPEC.md section 7.14). `case.json` gives the app spec files (`files`, as path and text), or a manifest (`manifest`), and the `counts` of `findings.json`, or `null` for no `findings.json`. A case of the adjudications (SPEC.md section 7.17) also gives `answers`, the list of `findings.json`, and `adjudications`, the text of `adjudications.jsonl`. `expect_verdict.json` is the expected `verdict.json`. I wrote each expected file by hand. `tests/test_verdict.py` reads the limits of the spec files into the manifest, writes `findings.json`, writes `adjudications.jsonl` if the case has it, builds `verdict.json`, and compares the 2 files.

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
| `adjudications_pass` | 2 mismatches with the outcomes `key_wrong` and `both_acceptable`. The count after the adjudications is 0, so the limit of 0 passes. `count` stays 2. |
| `adjudications_open_and_agent_wrong` | 3 mismatches: 1 `key_wrong`, 1 `agent_wrong` and 1 open. The count after the adjudications is 2, and the limit is 1, so the verdict is `fail`. |
| `adjudications_last_row` | 2 rows for one turn: `key_wrong`, then `agent_wrong`. The last row is the current outcome, so the mismatch counts. |
| `adjudications_unknown_outcome` | A row with an outcome that is not in the closed set. No row of the file applies, each mismatch is open, and the verdict has a problem. |
| `adjudications_no_author` | A row with an author of only white space is a problem. |
| `adjudications_turn_with_no_mismatch` | A row for a turn whose answer matches is a problem. |
| `adjudications_other_question` | A row with the question of another turn is a problem. |
