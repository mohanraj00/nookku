# Codex release proofs

The [run record](codex-0.5.5.json) gives the candidate method, commands, file hashes and tested harness versions. The base is [merged main](https://github.com/mohanraj00/nookku/commit/3024299478c7a2941e6a9ef52faf46232c178918). I set the package and plugin version fields to the candidate version for the runs, then restored those files. The release PR will set the version.

The final run of each listed command passed. The [trusted gate](../codex-gate/gate.json) also passed. Each proof ran in the main checkout with its existing Codex homes. No trust setting changed. The result files record the tested versions.

## Spec citation check

The [first project-hook spec-class run](../spec-classes/hooks-codex-run1.json) failed because the old checker accepted only `APP_SPEC.md` citations. The evaluation cited `spec/1.md`, the sealed copy added by [#471](https://github.com/mohanraj00/nookku/issues/471). It found the planted defects and left the records intact.

The [proof](../../scripts/proof_spec_classes.py) now accepts the original path or the correct sealed-copy path. It reads the class sections from the sealed copy. The [regression checks](../../tests/test_proof_gaps.py) reject a wrong file, section or turn. Both setups passed with this checker.

The [next project-hook run](../spec-classes/hooks-codex-run2.json) found a real defect in the control reply: the toy agent exceeded the [sentence limit](../../examples/toy-shop-full/APP_SPEC.md). The evaluator correctly reported it. I kept the failed result and made an unchanged repeat. The [final run](../spec-classes/hooks-codex.json) passed. These runs do not give a failure rate.

The [OpenTelemetry measurement](../otel/codex.json) still found no data from `OTEL_*`. The [Codex app usage proof](../performance/codex-app.json) compares app-server notifications, rollout usage and the per-turn record. Its repeat-total field gives the measured limit of that run.
