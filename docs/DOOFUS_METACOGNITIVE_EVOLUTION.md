# Doofus Metacognitive Evolution

Doofus includes an experimental metacognitive cortex that predicts whether an
evolutionary cycle will improve fitness, records that prediction before the
outcome exists, scores the prediction afterward, and uses only calibrated
evidence to recommend search strategy and effort.

## Runtime modes

`DOOFUS_METACOGNITION_MODE` accepts four values:

| Mode | Runtime effect |
|---|---|
| `off` | No monitoring or control |
| `shadow` | Record predictions, recommendations, outcomes, and calibration only |
| `advisory` | Expose recommendations without changing the cycle |
| `bounded` | Apply candidate count, A-Evolve portfolio, arena budget, abstention, and early-stop decisions inside existing hard limits |

`shadow` is the default. The subsystem remains experimental in every mode until
the MC-1 through MC-6 evidence gates pass.

## Evidence loop

Before a cycle, `doofus/metacognition/monitor.py` builds a typed state from the
metrics database, archives, capsules, arena results, historical prediction
accuracy, budget state, and current checkpoint. The controller writes a
prediction row before candidate generation. It contains:

- predicted fitness and interval;
- probability of non-regression;
- model, behavioral, evidential, and final control confidence;
- task difficulty and knowledge-boundary classification;
- selected strategy, control action, and requested candidate count;
- progress, noise, saturation, and regression signals.

After the cycle, the evaluator records actual and noise-adjusted gain, causal
confidence, calibration error, episodic memory, failure memory, and eligible
metacognitive genes. A single observation receives low causal confidence;
replicated gains, matched baselines, and stable environments are required for a
strong causal claim.

## Control and authority

The deterministic council separates four evidence roles: introspector,
empiricist, skeptic, and controller. No role can authorize itself. In bounded
mode, the final decision can only reduce or reallocate permissions already
granted by the existing runtime.

The following surfaces are constitutionally outside the mutation boundary:

- kill switches;
- protected roots;
- secret isolation;
- path containment;
- budget hard caps;
- write authorization;
- rollback enforcement;
- promotion gates.

Stronger-model escalation is never granted by the cortex. It must pass the
existing provider and operator authority path. The sealed FSF types in
`doofus/metacognition/fsf_contract.py` validate bounded mandates and proposal
envelopes without granting Doofus any Blunder authority.

## Memory and meta-metacognition

The metrics database stores individual control episodes, failure types,
strategic aggregates, and reusable metacognitive genes. Every 20 completed
cycles, the outermost loop may evaluate threshold challengers on chronological
training and held-out episodes. It requires at least 30 resolved predictions and
promotes only when both training and holdout utility improve. Safety fields are
not part of the evolvable policy schema.

## Research gates

`doofus/arenas/metacognitive/evaluator.py` reports nine arenas and six claims:

| Claim | Required proof |
|---|---|
| MC-1 | Confidence tracks observed success with bounded calibration error |
| MC-2 | Contextual selection beats fixed strategies on matched replay cases |
| MC-3 | Equal or better gain with fewer candidates, calls, or dollars |
| MC-4 | Abstention avoids non-improving generations |
| MC-5 | Policies transfer to held-out targets |
| MC-6 | Held-out meta-policy promotion improves utility without weakening safety |

Missing counterfactual, transfer, adversarial, or holdout evidence is reported
as `insufficient_*`; it is never converted into a pass. The dashboard's
Metacognition tab shows current state, calibration, prediction-versus-actual
charts, policy lineage, interoception diagnosis, and research-gate statuses.
