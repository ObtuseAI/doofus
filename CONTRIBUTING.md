# Contributing

Doofus welcomes focused issues, reproducible experiments, benchmark tasks, and
pull requests.

1. State the hypothesis and the evidence that would falsify it.
2. Keep training objectives separate from held-out evaluation.
3. Preserve dry-run defaults, path containment, provider-secret isolation,
   budgets, snapshots, rollback, and promotion gates.
4. Add the smallest meaningful behavioral, benchmark, recovery, or smoke test.
5. Run `python -m pytest tests -q` and `ruff check .`.
6. Report seeds, task versions, exclusions, uncertainty, and residual risk.

Do not submit provider credentials, private runtime databases, workstation
paths, model outputs presented as ground truth, or performance claims without
reproducible evidence.

Contributions are licensed under the [MIT License](LICENSE).
