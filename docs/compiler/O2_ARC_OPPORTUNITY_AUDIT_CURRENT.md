# Current O2 ARC semantic reconciliation

This is the corrected current report. The original
`o2_arc_opportunity_audit.json` remains immutable historical evidence of the
O2.8.5 audit error.

The root cause was a split proof boundary: the audit treated generic
escape/post-dominance classification as `PROVABLE_NOW`, while production also
required exact ownership provenance and rejected unsupported ownership
categories. `OwnershipEscapeAnalysis.classify_arc_pair` is now the canonical
semantic authority used by both the audit and `LocalARCEliminator`.

## Current census

- Production O2: **53 retains / 924 releases**; **0 pairs eliminated**.
- Candidates: **26**.
- Semantically provable: **0**.
- Primary classifications: **13 blocked by provenance**, **12 blocked by
  nested aggregate ownership**, **1 blocked by escape**.
- Phase 1 same-block eligible: **0**.
- Phase 2 straight-line multi-block eligible: **0**.
- `LocalARCEliminator` remains enabled as validated, fail-closed dormant
  infrastructure; it makes no production rewrite on this corpus.
- The highest-count next precision blocker is exact ownership provenance (13),
  narrowly ahead of nested aggregate provenance (12). Its observed causes are
  unsupported instructions (6), unknown external calls (4), and other unknown
  identity (3).

The two corpus failures are unchanged unsupported frontend/backend examples
(`newton_system.ae` and `probandoNR.ae`) and are reported deterministically.

## Reconciliation of the 12 historical `PROVABLE_NOW` sites

| Site (function; retain → release) | Correct semantic result | Provenance | Productive rejection |
|---|---|---|---|
| `loadLedger`; `then0:4` → `then0:6` | nested aggregate | exact | aggregate |
| `decodeLedger`; `merge79:0` → `merge61:14` | provenance | unknown external call | different identity |
| `decodeLedger`; `merge87:0` → `merge87:12` | provenance | other unknown | different identity |
| `decodeLedger`; `merge87:1` → `merge87:13` | provenance | other unknown | different identity |
| `decodeLedger`; `merge87:2` → `merge87:11` | provenance | other unknown | different identity |
| `decodeLedger`; `merge90:2` → `merge90:5` | nested aggregate | exact | aggregate |
| `decodeFailure`; `entry:1` → `entry:3` | nested aggregate | exact | aggregate |
| `readControlLine`; `merge2:5` → `merge2:7` | provenance | unknown external call | different identity |
| `requireHeaderLine`; `merge5:3` → `merge5:5` | nested aggregate | exact | aggregate |
| `loadForCommand`; `then0:3` → `then0:5` | nested aggregate | exact | aggregate |
| `runDemo`; `entry:2` → `logic.merge5:33` | provenance | unsupported instruction | different identity |
| `runDemo`; `entry:4` → `logic.merge5:32` | provenance | unsupported instruction | different identity |

The deterministic schema-v2 report is generated with:

```bash
python scripts/o2_arc_opportunity_audit.py
```

Every candidate includes provenance, escape, ownership state,
dominance/post-dominance, productive classification, and final rejection.

