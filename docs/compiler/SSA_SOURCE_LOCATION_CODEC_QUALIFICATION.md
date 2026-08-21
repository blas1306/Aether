# RUST-3.A2 — SSA source-location codec completeness

Decision: `SSA_SOURCE_LOCATION_CODEC_QUALIFIED`

Schema-v2 already represented every required `source_location`; it was not
changed.  The Python SSA model/constructor adapter omitted that field for six
instruction kinds: `array_copy`, `array_get`, `array_slice`, `list_copy`,
`list_get`, and `list_slice`.  The encoder consequently emitted `null` after a
Rust DTO had been decoded.  Those six dataclasses now retain the wire value.
Together with `binary_op`, `call`, `invoke`, and `pack_exception`, all ten
schema-capable instruction kinds have adversarial present/absent round trips.

The executable matrix in `scripts/audit_ssa_source_location_codec.py` audits
all 77 instruction dataclasses and records model support, schema
representability, encoder propagation, decoder propagation, constructor
assignment, and round-trip preservation.  The same generic dataclass adapter
also propagates the audited lossless metadata: `transferred_storage`,
`bounds_checked`, aggregate and nominal-struct metadata, class/interface
witness metadata, erased layouts, exception metadata, and function-reference
metadata.  No second codec loss of this shape was found.

## Ten-program failure analysis

The failures were all the same constructor-boundary defect.  The first lost
instruction in each Rust DTO was:

| File | Function/block/instruction | Kind | Loss |
|---|---|---|---|
| `benchmarks/list_for_sum.ae` | `main/for.body1/0` | `list_get` | `{line:6,column:9,path:null}` became `None` |
| `examples/Sorts/Main.ae` | `__ae_m8_Sortings__function_10_bubbleSort/entry/0` | `array_copy` | `{line:9,column:29,path:null}` became `None` |
| `examples/Sorts/Sortings.ae` | `bubbleSort/entry/0` | `array_copy` | `{line:9,column:29,path:null}` became `None` |
| `examples/aggregate_collections/particles.ae` | `main/for.body0/0` | `array_get` | `{line:19,column:5,path:null}` became `None` |
| `examples/esPrimo2.ae` | `esPrimo2/for.body1/0` | `list_get` | `{line:19,column:2,path:null}` became `None` |
| `examples/expense_tracker/Main.ae` | `__ae_m11_Persistence__function_12_encodeLedger/for.body0/0` | `list_get` | `{line:469,column:5,path:null}` became `None` |
| `examples/expense_tracker/Persistence.ae` | `__ae_m11_Persistence__function_12_encodeLedger/for.body0/0` | `list_get` | `{line:469,column:5,path:null}` became `None` |
| `examples/expense_tracker/Reports.ae` | `__ae_m7_Reports__function_9_summarize/for.body0/0` | `list_get` | `{line:16,column:5,path:null}` became `None` |
| `examples/llvm/list_copy.ae` | `main/entry/4` | `list_copy` | `{line:3,column:24,path:null}` became `None` |
| `examples/llvm/list_for_sum.ae` | `main/for.body0/0` | `list_get` | `{line:4,column:5,path:null}` became `None` |

The exact loss point was `_ir_instruction_to_ssa`: it only passed fields
declared by the target SSA dataclass.  Rust legitimately exercised collection
locations that Python SSA could not previously retain.

## Gates and A1 explanation

After correction, lifecycle parity, Rust verification/import, exact Python
reserialization, and determinism are each **116/116**.  Canonical Python-vs-Rust
SSA remains **106/116**.  The residual is not codec loss: Python lowering still
constructs the affected collection SSA operations without forwarding their
source locations, while Rust does.  Per milestone scope, no lowering algorithm
was changed; that residual is classified for the next lowering milestone.

RUST-3.A1's 116/116 claim was true for its tested domain.  Its corpus began with
Python-produced SSA, whose affected collection instructions lacked these
locations, and its field inventory checked dataclass/schema representability,
not adversarial decoder assignment from Rust-populated DTOs.  A1 remains frozen.
The new ten-kind adversarial tests prevent that blind spot from recurring.
