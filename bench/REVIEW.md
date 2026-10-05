# How to label bench/review.csv

Each row is one break that the audit found. The row does not show the arm, the harness or the cell. `bench/review-key.json` has that, so do not open it before you finish.

1. Open `bench/review.csv` in a spreadsheet.
2. For each row, compare `tester_message` with `agent_received`, and `agent_reply` with `shown_to_tester`. `first_difference` is the index of the first different character.
3. Write one label in the `label` column. Use the `note` column for anything that a label does not cover.
4. Save the file as CSV with UTF-8.

| Label | Use it when |
|---|---|
| `whitespace_only` | Only spaces, tabs or line ends changed. |
| `characters_changed` | Characters changed, but the words keep their meaning (for example accents or quotes). |
| `words_changed` | Words changed, were added or were removed. |
| `operator_wrote` | The operator sent or showed a message of its own (for example it answered the agent's question itself, or showed a reply from another turn). |
| `retry_after_error` | The operator sent the same message again after an error from the agent. |
| `not_sent` | The operator did not send the tester's message. |
| `scorer_error` | The audit is wrong: there is no real break. |

If a row fits two labels, use the more serious one. The order is `operator_wrote`, `words_changed`, `not_sent`, `characters_changed`, `retry_after_error`, `whitespace_only`. Write the second label in `note`.

After you save the file, `python bench/score.py` keeps your labels, and the report counts them.
