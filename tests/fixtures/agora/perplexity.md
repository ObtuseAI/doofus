1. Treat the simplest viable baseline as an identity transform with explicit provenance rather than an elaborate optimizer.
2. The mechanism can be supported only by empirical equality checks; source existence alone does not verify behavior.
3. Relevant prior art is ordinary pure-function contract testing, so novelty should remain conservative.
4. The likely failure is confusing a passing scalar example with general JSON preservation.
5. Run differential cases over scalars and structures, then compare hashes and exact outputs.
6. Confidence: 0.74
