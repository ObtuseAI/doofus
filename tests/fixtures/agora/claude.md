1. Build a receipt-carrying identity mechanism in which the returned value is paired conceptually with a deterministic contract check.
2. The mechanism should remain a pure function and must not consult files, environment state, clocks, or the network.
3. The invariant is exact structural equality between the JSON input value and the output value.
4. A fatal flaw would be serialization-dependent mutation or false confidence from only testing positive integers.
5. Falsify it with null, negative, nested, empty, and repeated inputs across independent source artifacts.
6. Confidence: 0.79
