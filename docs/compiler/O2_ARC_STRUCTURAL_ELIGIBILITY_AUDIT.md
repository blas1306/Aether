# O2.8.7 ARC structural eligibility audit

## Scope and result

This is an audit-only milestone over the current lifecycle-expanded O2 SSA.
It uses the canonical ownership analysis and only inspects pairs that it marks
semantically provable. It does not run an ARC rewrite. The deterministic
instrumentation is `scripts/o2_arc_structural_eligibility_audit.py`.

**Recommendation: `PROCEED_TO_NESTED_AGGREGATE_PROVENANCE`.** Neither current
pair can be enabled by one small structural rule. Both cross the same large,
branching region and need path/join proof, call-effect knowledge, and region
effect reasoning. The 12 nested-aggregate blockers offer substantially more
value than these two cold real-workload pairs.

## Exact pairs

Both pairs are in the real workload `examples/expense_tracker/Main.ae`, in
`__ae_m9___entry____function_7_runDemo`, at loop depth 0.

| SSA | Type | retain | release | root | ownership | semantic | Phase 1 | Phase 2 |
|---|---|---|---|---|---|---|---|---|
| `1` | `StringType()` | `entry:2` | `logic.merge5:33` | `fresh:1` | owned | `PROVABLE_NOW` | no | no |
| `2` | `StringType()` | `entry:4` | `logic.merge5:32` | `fresh:2` | owned | `PROVABLE_NOW` | no | no |

The constants are respectively `" 2 "` and `"\t250.0\n"`. Exact provenance
comes directly from their `SSAConst` definitions; neither proof depends on the
O2.8.6 same-root phi rule.

## Deterministic CFG slice

The minimal retain-to-release slice is identical for both pairs (only endpoint
indices differ):

```text
entry -> {logic.short0, logic.rhs0} -> logic.merge0
logic.merge0 -> {direct, then1} -> merge1
merge1 -> {logic.short2, logic.rhs2} -> logic.merge2
logic.merge2 -> {logic.short3, logic.rhs3} -> logic.merge3
logic.merge3 -> {logic.short4, logic.rhs4} -> logic.merge4
logic.merge4 -> {logic.short5, logic.rhs5} -> logic.merge5
```

All 18 blocks and all edges are normal. There are six binary decisions, 64
normal paths, no exceptional path, no backedge, and no path exiting before the
release. Each arm ends in `SSAJump`; each decision starts with `SSABranch`.
The six merge blocks have two predecessors each. They contain seven phis:
one each in `logic.merge0`, `logic.merge2` through `logic.merge5`, and two in
`merge1`. These phis merge unrelated scalar values, not SSA `1` or `2`, so
they do not alter pair identity or ownership role. Retain is present before
every incoming path and the single release balances the same ownership edge.

The generated audit contains the stable block order, predecessor/successor
edge kind, terminator, notable instruction sites, and all 64 minimal path
summaries. This compact rendering is the human-readable equivalent.

## Structural blocker and graph proofs

For both pairs the primary blocker is `DIFFERENT_BLOCK_BRANCH`: Phase 2's
straight-line proof stops immediately because `entry` ends in `SSABranch`.
Secondary blockers are `MULTIPLE_PATHS`, `JOIN`, `PHI`, `CALL`, `STORE`, and
`UNKNOWN_REGION_EFFECT`. Dominance alone is therefore insufficient.

For each pair:

- retain dominates release: yes;
- retain dominates every relevant direct use: yes;
- release postdominates retain: yes;
- release postdominates every relevant direct use: yes;
- dominance/postdominance counterexample: none;
- exactly one path: no (64 normal paths);
- exceptional alternate path, loop-carried path, or exit without release: no.

## Calls, exceptions, loops, and interference

The region contains eight direct calls and eight runtime-helper calls, plus
side-effecting print operations. There are no indirect/interface calls and no
`invoke`, catch, cleanup, rethrow, or propagation edges. The existing Phase
1/2 policy rejects calls conservatively. Crossing this region would require
trusted direct/helper summaries and a proof for other region effects; there is
no call-free structural extension for either pair. Calls are recorded per site
with `may_throw`, read-only, and ownership-effect fields. Unknown effects fail
closed.

The region also contains four stores. It has no loop, header, latch, preheader,
exit, or per-iteration ownership question. For each identity the only direct
ownership operations are its retain and matching release: no intervening
retain/release, destroy, move/consume, field/collection store of that identity,
interface box, return, or escape was found. The unrelated calls and stores are
still an unknown-region-effect barrier.

## Extension hypotheses and risk

An acyclic-diamond or identical-state join rule alone would get past only the
first structural check and unlock zero pairs: subsequent calls and effects
remain rejected. A call-summary rule alone also unlocks zero because Phase 2
still rejects the branches. Supporting either pair therefore needs multiple
new capabilities: path/join proof, trusted call effects, and region-effect
reasoning. That is path-sensitive rather than a small Phase 3 rule, so risk is
**HIGH** (new verifier proof surface and sanitizer exposure). Because both
pairs share the region, there is no uniquely cheap single case.

The two candidates are real-workload but cold, loop-depth-zero test/demo code;
estimated productive relevance is LOW and removal is not on a hot path. A
single proposed rule unlocks 0 of the 2 and 0 additional candidates in the
current 26-candidate corpus.

## Comparison and conclusion

| Opportunity | candidates | relevance | cost/risk | future enabling value |
|---|---:|---|---|---|
| Current structural pairs | 2 | real, cold demo path | high/high; multiple capabilities | limited |
| Nested aggregates | 12 | real workloads | analysis work; fail-closed provenance | high |

The recommendation follows the milestone rule: the structural cases are
low-value and require complex/path-sensitive reasoning, while nested aggregate
provenance is the largest blocker class and can improve the semantic foundation
without weakening structural safety.

No LocalARC code, ARC insertion/removal, O0/O1/O2 profile, production codegen,
historical baseline, or transformation test was changed. No commit is created
by this audit.
