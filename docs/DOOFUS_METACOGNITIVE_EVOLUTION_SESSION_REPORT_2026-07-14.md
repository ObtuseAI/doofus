# Doofus Metacognitive Evolution Session Report

## Session identity

- Date: 2026-07-14
- Workspace: `C:\Users\developer\doofus`
- Branch: `doofus-gen1637-postlive-certification-v1`
- Starting HEAD: `5db1071`
- Delivery state: publication through a review branch and draft pull request was requested after validation
- Shared review packet: `\\fileserver\shared\Doofus-Metacognitive-Evolution-20260714`
- Runtime impact: no live model calls, no canonical runtime cycle, and no safety or authority gate changes

## Implemented architecture

Doofus now has five explicit nested loops. Candidate, population, and evolver
loops remain intact. The new metacognitive loop predicts and regulates search,
and the meta-metacognitive loop evaluates controller-policy challengers on held-
out episodes.

The implementation includes:

- typed cognitive state, uncertainty, confidence, progress, strategy,
  allocation, council, and control-decision contracts;
- prediction-before-outcome, event, episode, failure, gene, and policy-
  evaluation SQLite ledgers;
- separate model, behavioral, evidential, and final control confidence;
- Brier score, expected calibration error, confidence/fitness correlation,
  false-confidence rate, abstention quality, and interval coverage;
- task-difficulty and knowledge-boundary classification;
- contextual strategy utility across executable and advisory-only strategies;
- dynamic candidate, arena, replay, simulation, reviewer, and wall-clock advice;
- `off`, `shadow`, `advisory`, and `bounded` runtime modes with `shadow` as
  the default;
- bounded candidate count, A-Evolve algorithm portfolio, arena budget,
  abstention, and online early-termination integration;
- falsifiable critique and disconfirmation-test contracts;
- episodic, strategic, failure, and metacognitive-gene memory;
- causal confidence and noise-adjusted gain, with a deliberately low score for
  unreplicated observations;
- introspector, empiricist, skeptic, and controller evidence roles merged by a
  deterministic council;
- interoceptive diagnostics for convergence, lineage concentration,
  oscillation, calibration drift, evaluation instability, resource stress,
  model dependency, and capability atrophy;
- held-out meta-policy challenger evaluation with a minimum of 30 resolved
  episodes and no mutable safety fields;
- nine metacognitive research arenas and explicit MC-1 through MC-6 statuses;
- a sealed Doofus/Blunder mandate and proposal schema that leaves authority
  ownership with Blunder;
- a Metacognition dashboard tab, prediction-versus-actual calibration chart,
  policy/memory snapshots, arena statuses, and event table;
- operator documentation and environment examples.

## Immutable authority boundary

The metacognitive cortex cannot mutate or bypass:

- kill switches;
- protected roots;
- secret isolation;
- path containment;
- budget hard caps;
- write authorization;
- rollback enforcement;
- promotion gates.

Stronger-model escalation is advisory-only unless the existing provider and
operator authority path grants it. The default shadow mode never changes a
runtime decision.

## Research status

The subsystem is classified `METACOGNITIVE_CORTEX_EXPERIMENTAL`. No MC claim is
pre-certified. Missing matched counterfactual replays, held-out repositories,
adversarial cases, or held-out policy promotions remain `insufficient_*` rather
than being upgraded to pass.

## Validation evidence

- Python compile/import smoke: pass
- Fresh SQLite schema smoke: pass; six `metacognitive_*` tables created
- Diff whitespace validation: pass
- Focused architecture/integration/dashboard/isolation suite: `37 passed`
- Repository-wide split execution: `346 passed`, `3 skipped`, three unrelated
  baseline failures, and one unrelated legacy timeout (`353 collected`)

Unrelated baseline results intentionally left outside this change:

1. `test_init_timeout_containment_baseline.py::test_checkpoint_backup_created`
   patches checkpoint source modules but not the checkpoint constants already
   bound by `checkpoint_baseline.py`; returned backup mapping is empty.
2. `test_self_improvement_catalog.py::test_next_cycle_seeds` expects at least
   20 seeds but the current workspace produces 15.
3. `test_shared_improvement_feed.py::test_main_dry_run_writes_schema` expects
   `artifacts/doofus/shared-improvement-feed-v1/FEED_SCHEMA.json`, which the
   existing dry-run path did not create.
4. `test_doofus_windows_runtime_manager.py::test_runtime_manager_once` did not
   complete within 120 seconds. It invokes the existing Windows repair path and
   is unrelated to metacognition.

The focused metacognition suite uses isolated temporary runtime/state paths and
does not access the canonical metrics database.

## Review notes

- Default-branch integration remains operator-controlled through the GitHub pull request.
- The project virtual environment now contains its already-declared `dev`
  dependency (`pytest`); no new project dependency was added.
- Recommended rollout is to keep `DOOFUS_METACOGNITION_MODE=shadow` until the
  dashboard accumulates enough resolved episodes to evaluate calibration and
  transfer honestly.
