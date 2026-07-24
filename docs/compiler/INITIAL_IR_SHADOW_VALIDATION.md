# Initial IR Shadow Validation — Phase 4.4

## Scope and conclusion

Phase 4.4 was run from repository revision `c52fa68` on 2026-07-24 with
Python 3.14.4, rustc 1.95.0, cargo 1.95.0, and Ubuntu clang 21.1.8.
The working tree changes described here were present during the final runs.

Rust remains strictly observational. The only production integration point is
still an explicitly supplied `ShadowVerifierCoordinator`; the coordinator
runs `IRVerifier` first and returns or re-raises that Python result. The new
full-suite harness lives under `tests/`, requires an explicit verifier path,
and restores `IRBackend.__init__` after the pytest session. It adds no
environment variable, compiler option, executable discovery, fallback, cache,
telemetry, concurrency, or PyO3 path.

The run found one genuine Rust verifier defect: cross-block dominance was
being enforced in retained unreachable loop-increment blocks, contradicting
the Python Initial IR verifier's IRV-022 local-check policy. Three request
hashes produced five unexpected outcome divergences. The narrow Rust fix now
accepts all three minimized compiler-generated shapes; no divergence rule was
added. The final full-suite result has zero unexpected divergences.

This is strong local validation evidence, but it is not sufficient by itself
to move authority in Phase 4.5. The documented IRV-024 outcome divergence,
invariant coverage gaps, missing Python structural diagnostic context,
test-only integration, and absence of a sustained real-world soak remain
material blockers.

## Call-path audit

There are no unresolved `UNKNOWN` paths.

| File and symbol | Route | Classification without the test harness | Phase 4.4 result |
| --- | --- | --- | --- |
| `src/aether/pipeline.py::IRBackend.lower` | checked program to Initial IR | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Reaches shadow when the explicit backend coordinator is injected. |
| `IRBackend.verify` / `lower_verified` | authoritative Initial IR boundary | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | `INITIAL`; Python remains authoritative. |
| `IRBackend.optimize_verified` | lifecycle expansion, IR optimization, second verification | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | `POST_OPTIMIZATION`; never deduplicated from `INITIAL`. |
| `IRBackend.run` | Initial IR interpreter | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Covered through normal CLI/tests. |
| `SSAPipeline.lower_ir` / `run`, `lower_to_verified_ssa` | Initial IR to SSA | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Covered through SSA, LLVM, native, examples, and benchmarks. |
| `src/aether/backend/llvm/build.py::LLVMBuilder.emit_llvm` / `build` | Initial IR, SSA, LLVM, clang | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Covered through native tests. |
| `src/aether/cli.py::_execute_file` (`ir`) | IR interpretation | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Covered. |
| `src/aether/cli.py::_emit_ir` | IR print and optional O0/O1/O2 optimization | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Initial and post-optimization covered. |
| `_emit_ssa`, `_emit_llvm`, `_build_native`, default/run LLVM route | SSA/LLVM/native | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | Covered. |
| `src/aether/benchmark.py::_build_ir`, `_run_ir_o1_optimizer`, `_build_ssa`, `_emit_llvm`, `_build_native` | benchmark layers | `SHADOW-CAPABLE-BUT-NOT-ENABLED` | All 10 repository benchmarks covered. |
| `src/aether/cli.py::_emit_cfg` | unchecked lowering for CFG visualization | `INTENTIONALLY-NOT-VERIFIED` | Still outside shadow; not counted as a failure. |
| direct `IRLowerer.lower`, `lower_to_ir` calls in focused tests | lowering component tests | `INTENTIONALLY-NOT-VERIFIED` unless followed by explicit Python verification | Not globally intercepted. |
| direct `IRVerifier(...).verify()` and `verify_module_normalized` | Python verifier unit/API tests | `INTENTIONALLY-NOT-VERIFIED` by shadow | Preserved as Python-internal tests. |
| direct `ShadowVerifierCoordinator.verify` | external module/corpus observation | `SHADOW-COVERED` | Corpus reports use `EXTERNAL`. |
| CLI `--tokens`, `--ast`, `--check`, AST backend, REPL, LSP/editor paths | frontend/AST only | `DOES-NOT-PRODUCE-INITIAL-IR` | Not counted as shadow misses. |

Production `IRBackend` construction sites are
`src/aether/pipeline.py:196,222`, `src/aether/cli.py:599,640,669`, and
`src/aether/benchmark.py:216,237`. The only production direct Python
verifier sites are `src/aether/pipeline.py:115`,
`src/aether/ir/shadow_verifier.py:446`, and
`src/aether/ir/verification_result.py:103`.

Test `IRBackend` construction occurs in:

`test_alpt1_persistence.py`, `test_backend_feature_parity.py`,
`test_backend_print.py`, `test_collection_copy_phase2.py`,
`test_collection_migration_baseline.py`, `test_collection_slicing_phase3.py`,
`test_const_collection_borrowed_for.py`, `test_differential_parity.py`,
`test_entry_point.py`, `test_enum_native.py`, `test_eq_contract.py`,
`test_expression_functions_and_math.py`, `test_integer_arithmetic_safety.py`,
`test_integer_literals_i32.py`, `test_logical_not.py`,
`test_logical_short_circuit.py`, `test_native_modules.py`,
`test_numeric_backend_parity.py`, `test_pipeline.py`,
`test_process_arguments.py`, `test_scalar_math_native.py`,
`test_shadow_validation_harness.py`, `test_shadow_verifier.py`,
`test_ssa_repository_regression.py`, `test_string_concat_byte_length.py`,
`test_string_parsing.py`, `test_string_split.py`, `test_string_trim.py`,
`test_struct_backend_parity.py`, `test_text_file_io.py`,
`test_typed_callables.py`, `test_v1_profile_audit.py`, and
`test_vector_matrix_semantic_parity.py`.

Direct Python `IRVerifier` tests are intentionally retained in:

`test_array_p0_safety.py`, `test_array_slicing.py`,
`test_collection_copy_phase2.py`, `test_collection_slicing_phase3.py`,
`test_const_collection_borrowed_for.py`,
`test_control_flow_iteration_characterization.py`,
`test_control_flow_regression.py`, `test_enum_native.py`,
`test_eq_contract.py`, `test_for_backend.py`,
`test_integer_literals_i32.py`, `test_ir_aggregate_metadata_verifier.py`,
`test_ir_borrow_verifier.py`, `test_ir_control_flow_instruction_dto.py`,
`test_ir_lifecycle.py`, `test_ir_linear_algebra_instruction_dto.py`,
`test_ir_return_path_characterization.py`,
`test_ir_verification_result.py`, `test_ir_verifier.py`,
`test_list_backend.py`, `test_list_bounds.py`, `test_logical_not.py`,
`test_matrix_column_mul.py`, `test_outer_product.py`,
`test_string_concat_byte_length.py`, `test_string_parsing.py`,
`test_string_split.py`, `test_string_trim.py`,
`test_struct_collections_native.py`, `test_typed_callables.py`,
`test_vector_dot.py`, and `test_vector_matrix_indexing.py`.

## Validation harness

`tests/shadow_validation_harness.py::ShadowValidationHarness`:

1. resolves the explicitly supplied subprocess executable to an absolute path;
2. constructs `SubprocessRustVerifierClient`,
   `ShadowVerifierCoordinator`, and a session-local report sink;
3. injects only into otherwise unconfigured `IRBackend` instances;
4. leaves explicitly configured backends untouched;
5. excludes the shadow infrastructure tests whose contract requires disabled
   mode;
6. counts pytest tests independently from verification observations;
7. aggregates classifications, stages, Python outcomes, invariants, hashes,
   duplicates, bounded timings, and non-parity provenance;
8. writes sorted, indented, deterministic-key-order JSON; and
9. restores the exact prior constructor after the session.

Activation is explicit and test-only:

```text
pytest tests \
  --shadow-validation-executable compiler-rs/target/debug/aether-ir-verifier \
  --shadow-validation-output build/shadow-validation-summary.json
```

No build artifact is committed. The transient final summary is
`build/shadow-validation-summary.json`.

## Populations and totals

### Full Python suite

| Measure | Result |
| --- | ---: |
| pytest tests collected | 4,199 |
| tests exercising the injected shadow | 963 |
| shadow observations | 1,675 |
| distinct request hashes | 644 |
| repeated observations | 1,031 |
| Python accepted observations | 1,674 |
| Python rejected observations | 1 |
| injected backend constructions | 1,618 |

The full suite result was 4,194 passed, 1 skipped, and the same 4 pre-existing
V1 example-manifest failures described below. A pytest pass is not treated as
a shadow observation.

Final full-suite classifications:

| Classification | Total |
| --- | ---: |
| `MATCH_ACCEPTED` | 1,674 |
| `MATCH_REJECTED_SEMANTIC` | 1 |
| every unexpected divergence | 0 |
| Rust infrastructure failure | 0 |
| Rust integration failure | 0 |

By stage:

| Stage | Accepted match | Rejected semantic match | Total |
| --- | ---: | ---: | ---: |
| `INITIAL` | 1,585 | 0 | 1,585 |
| `POST_OPTIMIZATION` | 89 | 1 | 90 |

### Rust migration corpus

All 130 entries were materialized. The 128 schema-v1-transportable requests
had 128 distinct hashes and retained the Phase 4.3 baseline:

| Classification | Total |
| --- | ---: |
| `MATCH_ACCEPTED` | 64 |
| `MATCH_REJECTED_SEMANTIC` | 60 |
| `DOCUMENTED_DIAGNOSTIC_DIVERGENCE` | 3 |
| `DOCUMENTED_OUTCOME_DIVERGENCE` | 1 |
| unexpected / infrastructure / integration | 0 |

The exact existing documented rules and hashes were unchanged. The two
explicit harness skips remain:

- `lifecycle-non-storage-destination`: DTO `storage_shape`;
- `integer-constant-out-of-range`: DTO `signed_i32_constant`.

### Repository examples and benchmarks

The repository regression discovered 103 `.ae` examples plus 10 benchmarks.
Ninety programs lowered to verified Initial IR and observed Rust; 23 did not
produce Initial IR and are not shadow failures:

`Miller-Rabbin.ae`, the three `Sorts` files, all seven `classes` files, all
three `interactive` files, the three `linear_algebra` files,
`lists/list_api.ae`, `minimos_cuadrados/MinimosCuadrados.ae`,
`nonlinear_systems/newton_system.ae`, `probando.ae`, `probandoNR.ae`, and
`pruebaException.ae`.

The V1 manifest contains 78 native-capable programs (68 executed and 10
declaration/module files) and 23 AST-only programs (14 executed). Their
existing stdout/stderr SHA-256 and exit-code assertions ran while shadow was
injected. Shadow caused no assertion change.

Both unmanifested LeetCode programs were separately validated:

| Example | Request hash | Result | Output/exit equivalence |
| --- | --- | --- | --- |
| `isPalindrome.ae` | `656d3f4b8d00e6e7ab53c09beaa68de67e53b064588e14b8d6595c46961f821c` | `MATCH_ACCEPTED` | identical; exit 0 |
| `twoSum.ae` | `0807b053baefba7ae4fb75e6d2a3b5ad62c7de199797c5bc3d520dfea1f8fe4b` | `MATCH_ACCEPTED` | identical; exit 0 |

Representative large integrated programs also matched: nested aggregate
collections (`ae4d08…f1bb`), numerical-method modules (`698747…9c0a`), and the
26-function expense tracker (`b95bb8…90d9`).

## Feature coverage

Every row below is an accepted, transportable observation at `INITIAL` unless
stated otherwise.

| Capability | Evidence | Request SHA-256 / result |
| --- | --- | --- |
| primitive scalar types, arithmetic | `lowered-add` | `7ed1be13bb0215e658b40ac02d1aa9ae3266a5e4cfadbd0a9841e1e6d2a2fc62` |
| comparisons and equality | `compare-int-lt`, `compare-string-eq` | `56ab6afa23d183f744b7c00a66c884562fb6472911469e690a7e2518d601ac4d`; `cc47df78c76608ceeeeb2951333eed85012236bb398158e8aaa8b408f607d3c3` |
| branches and loops | `lowered-if-else`, `lowered-while` | `e18a9938afcef85b0a8be0e56f9287038fab1e66222b73deb7c758f9353ea89e`; `6f494068f08bb40d5acaadc91bf5ba235c43f6f55d0a15b5ea111f1deca5a2f4` |
| calls, returns, parameters, local slots | `lowered-direct-call`, `lowered-local-store-load` | `981f6c642a490613dc7dc33208b5fc40e3a2afbb6d9f5357472ad376ef30d38c`; `ed33a62f0495ae721561551cce5209d02f6b22f1f460c8624bc3b614dd4e6dd6` |
| arrays and explicit copies | `collection-copy` | `eb0de5f4cc826525d5e654b428e2f2184291b570c66da7964a33ef28ac01c11b` |
| lists | `list-construction-read-properties` | `978b173ece2edc05e100e76d8541baa4118ebc16c9031b2ba8abe2ef4d00938c` |
| structs and lifecycle | `struct-default-init-destroy`, `lifecycle-operations` | `3fcc7141f4a412384df26ddf8dd8998502ff542306d49a97b7085e068847216a`; `e833cec86c60e6ea53144982ba26c2105fcc4c0891799b14bbd26102f8e2075c` |
| nested structs and aggregate equality | `aggregate_collections/particles.ae` | `ae4d08a708534ceacaa37e1d30e954c99ffb92e5ec90a60430c7a4e23748f1bb` |
| strings | `compare-string-eq`, `string-parse-builtin` | `cc47df78c76608ceeeeb2951333eed85012236bb398158e8aaa8b408f607d3c3`; `720f7e86a18a7e67541d25aa4e0f24f0f66c5b4591860de4a91b07ca6fdc8536` |
| enums | `enum-lowering` | `815ae3a6107938af68bc948faa4dcd2d971173d2dd098bb7e7dbbfb2d1b24139` |
| flattened modules and selective imports | numerical methods and expense tracker | `69874777fb9e9d638b7d4a4d09230f263256a67f7f2fc7d70b543a75f2759c0a`; `b95bb894d06b68c2d7e1926d33549b7280b023bda7d7ed9b45cf1208458090d9` |
| function references and indirect calls | `typed-callable` | `2013914e71d66850f308f095e1a73911568fe189cb474c1618f00287bde3721a` |
| numerical builtins and floating point | numerical methods, `int-to-double-cast` | `69874777fb9e9d638b7d4a4d09230f263256a67f7f2fc7d70b543a75f2759c0a`; `a978c490e54831e31188d92907390069dc5da6cabcf1aacd0e62355079d51f47` |
| printing | `hello.ae` | `41f7f46b8e6a9f5df3a9e1dcb4ebc8e12f3a08c7708085da10cdb1e92eb33177` |
| checked integer operations | `identity-cast-integer-power` plus modulo/division/overflow suites | `6d0c79a024719eaea716c0e6594db31e52d31c60ad91b4202a4b8ab582fb1ae7` |
| borrowed collection iteration | `lowered-borrowed-iteration` | `a12c5ab520fea4a36c5d6a3d9d24d2ad3c37c4cd7320db539adcf08a11cc39a1` |
| sorting | `sequence-sort` | `1ed63b37e1c2f153220cefd5a75351e218d03ca1eaadf66400a8cdd82c8097ae` |

Classes and interfaces are DTO-representable types but normal native lowering
rejects their capabilities before Initial IR, so there is no accepted
normal-pipeline class observation. AST-only error handling, interactive input,
and unsupported linear-algebra syntax likewise do not reach Initial IR.

## Rejection and invariant coverage

The transport corpus observes 42 distinct Python invariants as first
rejections (44 including the two nontransportable cases) and mentions 87 of
the 124 catalog invariants in `covers`. Sixty transportable rejected modules
match semantically; the Python side lacks the phase/function/block/instruction
context that Rust supplies, which prevents exact equality.

The 37 catalog invariants not named by any corpus `covers` entry are:

`IRV-001`, `002`, `003`, `009`, `010`, `011`, `015`, `016`, `022`, `023`,
`030`, `040`, `042`, `055`, `056`, `057`, `062`–`067`, `071`–`073`, `075`,
`078`–`085`, `087`, `088`, and `090`.

Many are exercised only by direct Python verifier tests, as intended. The
normal compiler pipeline almost always generates valid IR; the injected full
suite saw only one deliberate post-optimization Python rejection. Therefore
the external migration corpus, not normal compilation, remains the rejection
matrix authority. Exact per-invariant hashes and documented rules are emitted
under `python_invariants` in `build/shadow-validation-corpus.json`.

No broad divergence rule was created. IRV-031/032, IRV-050/026, IRV-036/028,
and the IRV-024/Rust-acceptance case remain the only exact hash-scoped rules.

Transportable first-rejection matrix:

| Python | Rust | N | Classification | SHA-256 | Rule |
| --- | --- | ---: | --- | --- | --- |
| IRV-004 | IRV-004 | 1 | `match_rejected_semantic` | `647f2a07e1bceb700c112b2eb0420d039ea99349008186765f57398785f36874` | — |
| IRV-005 | IRV-005 | 1 | `match_rejected_semantic` | `588079a69fc9a9b4a6b0a0abef0168f627c95425305d3bdc3930be9f5e2a22e0` | — |
| IRV-006 | IRV-006 | 1 | `match_rejected_semantic` | `0ed629e3f971d562136d2779f181b375c2168bfba6e1ea5a9852994dd42ab3be` | — |
| IRV-007 | IRV-007 | 1 | `match_rejected_semantic` | `3d66e88e404060da4d404c70365ec9a2252dbf35a1d0b59f45c2481a8b48b80b` | — |
| IRV-008 | IRV-008 | 1 | `match_rejected_semantic` | `5978a95457b1b2eba883cef9338c9ae35376d8847cae910612a885ce6b2b51e8` | — |
| IRV-017 | IRV-017 | 1 | `match_rejected_semantic` | `60b72728e48fbbacd6d0a14414711735dda9cf7e049186b453e7f6bc1db92062` | — |
| IRV-018 | IRV-018 | 1 | `match_rejected_semantic` | `2566a332d370ac53a9297dd4ce0abe73a4767846e183228c1bcc1864051e8c58` | — |
| IRV-019 | IRV-019 | 1 | `match_rejected_semantic` | `a3195e43bdd0e04be38620fb4e3d8e5daa27054234dd0222951c235cad1767b6` | — |
| IRV-020 | IRV-020 | 3 | `match_rejected_semantic` | `70039a8b369b30463219e4c6e5d22d12457c52d474fda4c38e468802b85461ee`<br>`353a13f8f32a056d4d89397dfa9683a1445a333f881bee9b25a400bcf4e791cf`<br>`a750b796058f911a6942e1442ae72ec71f810adeaa0f540c6e7823d582f8f74f` | — |
| IRV-021 | IRV-021 | 2 | `match_rejected_semantic` | `f9099a6b9a4652441de1b6d0258b26cde1645688bdb6845f6ee07c9c4db58639`<br>`25fb86e2d6f851ebc9ca23a88d72e429a382b5cda9ffb6a8e5f72a0996de3d7c` | — |
| IRV-024 | accepted | 1 | `documented_outcome_divergence` | `d635f6fc4c9e933e20442539c12409fcdc3de3da0938927f6b784c3002550baa` | non-void-path-without-return-graph-analysis |
| IRV-025 | IRV-025 | 1 | `match_rejected_semantic` | `9c26ffc567d4ef68be280e7316b9cbffea2dfb73f14649a0d3e51bf888279158` | — |
| IRV-026 | IRV-026 | 2 | `match_rejected_semantic` | `b763cdf25746349310142905352cb074532ac936d17dfbefb87364b20301070b`<br>`de26c7a423368149601bb615165d2b89651acac002b0fccef69a2c3bdd1f4f56` | — |
| IRV-028 | IRV-028 | 1 | `match_rejected_semantic` | `bb7e65cd835c5dbbb2307e07e9bacac2282110071442980049c75c3372531fee` | — |
| IRV-029 | IRV-029 | 1 | `match_rejected_semantic` | `3b7e4e6e3ef74bb240d970123a2e34ca4d9321dabffe75619548d460866c9505` | — |
| IRV-031 | IRV-032 | 1 | `documented_diagnostic_divergence` | `65b64a4021d20766e845fb23e48fd90c4992cf0f23936298e147f8b4eb6c095e` | undefined-slot-representation-import-model |
| IRV-032 | IRV-032 | 5 | `match_rejected_semantic` | `8f65fbe43df693ceb44c22452253b2ab99b51e03322317e2c25eeb6050050e99`<br>`ace314db9252d650caa8fc607d871d9f19d4c063356032f611a59d92b700742d`<br>`b63225a9a750388a3e349076da3c75e3332753b95a565d3b488a47e6c87c139a`<br>`73b010479f60037be3855fad7edebdef1388d4ce68e4374b5e1f6de1db32f33f`<br>`9535b314e59dca573d1d3a31188e76fe56470051f29896a2e2cfa05e98f7a9ed` | — |
| IRV-036 | IRV-028 | 1 | `documented_diagnostic_divergence` | `2b1463ad529acf1b86dccd04c89408431826d51d0a0bba8739830c4e46d30d1f` | inconsistent-branch-initialization-dataflow-semantics |
| IRV-041 | IRV-041 | 1 | `match_rejected_semantic` | `3fa7c5c310091b6acc049867abf082ebc2c244dedd85a5cb7f797e80e09ff9ec` | — |
| IRV-045 | IRV-045 | 1 | `match_rejected_semantic` | `e79c030c22abb87a17c14afccad937761d8fa652c2a607ef1334f20340601dc1` | — |
| IRV-049 | IRV-049 | 2 | `match_rejected_semantic` | `9f2baf6b782e270c04b84792543d2ab123684463d26fedcfdd1683510094abd2`<br>`b1b5371501a817b30aa09af6edfb3eedfc2c47859e8d61668b77758524f375d6` | — |
| IRV-050 | IRV-026 | 1 | `documented_diagnostic_divergence` | `90c0a3fccf6b737179d1feef9c32d11b3874edfccc3914facbd0df1d904803d9` | return-storage-after-move-first-failure-ordering |
| IRV-050 | IRV-050 | 4 | `match_rejected_semantic` | `afea543c3f2a9c1690dbaacc451e3f24b05555aee66c509ad0da1fe0ec8f0f29`<br>`9db9a57ddcdbebcc31c3b00a79dae4d14eacc70fa5e6e2708abf6021c744339f`<br>`56f6f7f2a61d06d80f210205cc51e50e29ec4543c95cceae265e96a6b83c4e22`<br>`573c497d525676e5534545b0d7d74e1acf784c784a46dc5eeba1ce3123e6b626` | — |
| IRV-052 | IRV-052 | 4 | `match_rejected_semantic` | `fbf8d103aa699cf36d7e8ffe8a51aaf6a0b197c57aaff5cbcdad6b619acf1199`<br>`a621f248faeeec3324c382218d570db3f74954ae2b39d469174a46757e118b39`<br>`c5197504bc761816d8b8a5e664692a73bb29d334598ccc9548eaf8f7fce7d658`<br>`9ec305fbc356762c2fd460478b35cb6bdfb57f53cf99f48795687cdaf857f9a9` | — |
| IRV-053 | IRV-053 | 1 | `match_rejected_semantic` | `3353c839717e1144e66256222a376b00ffa05f9a37942be12e35b23ef27e8436` | — |
| IRV-058 | IRV-058 | 1 | `match_rejected_semantic` | `41a4975cb6c4ad2e99690b9f238c81c691280f6a60b0725f5a5986466e8dafed` | — |
| IRV-059 | IRV-059 | 1 | `match_rejected_semantic` | `0d25bc602d712a8371df378585989a362e909bfa89151f27d223289fe4744042` | — |
| IRV-068 | IRV-068 | 1 | `match_rejected_semantic` | `a76aa7c11cb58ae44f9935eadb6605ff245f5aeae45f10b5cb8b775f6e872d87` | — |
| IRV-070 | IRV-070 | 2 | `match_rejected_semantic` | `05424b9d7eb8bc79024509063140da8869279af49699fdb40ad46211f65e958d`<br>`53d72aff6a8bbe84d9df413a7e83fbc0ce26164318732418e24fc91bc78b959e` | — |
| IRV-074 | IRV-074 | 1 | `match_rejected_semantic` | `7483aa898548272db13fc42640aa12178a7deb458a36587aa4f702d7ebb90a0f` | — |
| IRV-076 | IRV-076 | 6 | `match_rejected_semantic` | `f5bc207cbe47ffbb7d1c4174bce161a360cdad87bfb173c0432284731b5ea657`<br>`c7baef1373bb17377180a3b3e47fdd65c55fb19c0c2695e2814c8e458fc944c9`<br>`3bd8e462dd21732fd2b99ad219358f2e4ea62cdc2195b433a3451dd19f4388cd`<br>`584eefe32f992a340f282d02feddc9cbb1e208fcf10b51680c7c1bad15aadfb8`<br>`d1a3536fffe33b5759f995b463d5403533cdf1b4c6428ac409dd40b448b2d609`<br>`adb9f4d863b2b819c68e91c6c16f7b1c4f3d9ce6887d246bbb3cc576f511af07` | — |
| IRV-077 | IRV-077 | 1 | `match_rejected_semantic` | `327a084f972a6ee113060856b1632cf737f409e813be104d563edbb4cbf1713d` | — |
| IRV-091 | IRV-091 | 1 | `match_rejected_semantic` | `61f749ca0f246543b521d067c59903a2fc95ba84fca2d7f2e87d5c1d5b0b8774` | — |
| IRV-093 | IRV-093 | 1 | `match_rejected_semantic` | `d2ab63f3b8eb08c77240bb98c50375901d8f2ccc6b861d3acb660f1caf39d205` | — |
| IRV-100 | IRV-100 | 1 | `match_rejected_semantic` | `b2e5fb720b945f27e8f046a45a6723be38b9791b97bee1126ba82a47ead83226` | — |
| IRV-102 | IRV-102 | 1 | `match_rejected_semantic` | `03ab3a37c2d46c01cc966fc4c8b742c85d385144d3debf7fee2a31ad36cdfd0f` | — |
| IRV-103 | IRV-103 | 1 | `match_rejected_semantic` | `d5cca5e8f127b01046d23850ddb88a15837c19515228485051591a590fe0f5b1` | — |
| IRV-104 | IRV-104 | 1 | `match_rejected_semantic` | `7e92ae212437d4ee3f69575fe6dda93a7d2a50ceef4ea162a97ee2d1d3e8e3b5` | — |
| IRV-105 | IRV-105 | 1 | `match_rejected_semantic` | `f1d1901851ad81559391ea68e70351931255490f894bdba07241f2791d9e6346` | — |
| IRV-107 | IRV-107 | 1 | `match_rejected_semantic` | `889ac59e82ff02afd6c7eb4765b0c86b3be3fe78fbc4e7e87c50fa685b2cc13e` | — |
| IRV-118 | IRV-118 | 1 | `match_rejected_semantic` | `cf594cc063dc90bd988f3a8cf997ef1a4da7d5b343773d017b2741473e755df0` | — |
| IRV-119 | IRV-119 | 1 | `match_rejected_semantic` | `7401c743cda0b241534e056409f73b51a6403a869a5185493af8c0d51935e659` | — |
| IRV-122 | IRV-122 | 1 | `match_rejected_semantic` | `10f622aa1ef9d1078fc0f68ec10d3aaa84b2907079d49f0698eb60bf0b2fcb59` | — |

## Optimizer and native matrix

The registered Initial IR pass order is:

`ConstantFolder`, `LocalConstantPropagator`, `ConstantFolder`,
`AlgebraicSimplifier`, `DeadCodeEliminator`, `DeadStoreEliminator`,
`DeadCodeEliminator`.

All passes execute deterministically in optimizer tests. `constant_fold.ae`
changed through constant folding and dead-code elimination;
`local_const.ae` changed through local propagation, folding, dead-store
elimination, and dead-code elimination. Lifecycle expansion runs before the
optimizer and the second verification. There is no registered Initial IR CFG
simplification pass; this is an explicit coverage gap, not a skipped pass.

The three repository IR examples produced separate accepted initial and
post-optimization reports with changed hashes:

| Program | Initial | Post optimization |
| --- | --- | --- |
| `constant_fold.ae` | `1d588cfe316f0e5eb1f958724135b7a70ce6f9afed05a2ca0d3e45dfc3873683` | `e4e37c49a1666a21595563cc7a3bbe989fd290248e79098367312522407f7298` |
| `local_const.ae` | `52245244db11e90da7512f170f2f64da987776037317ef7607c389106c4301f7` | `90f030ad003f74626aa147b0d097be33f332add982d00c88c9df42894e10260d` |
| `sumTo.ae` | `d9ed030c9e8802495de291c7fc90d09ecf442955c55e5183f9623ebe9d02d838` | `d7ccb1f7e7175d8574d072d1c05a5b4d86f1ec9ebd4c5da786e599eda83bb86d` |

An identity optimizer still emits two reports even if hashes are equal.

Native `-O0`, `-O1`, and `-O2` clang-profile tests for ALPT1 and text I/O all
compiled and executed with unchanged stdout and exit codes. The native path
always observes Initial IR before SSA/LLVM; clang optimization does not change
the canonical Initial IR request. Accepted and deliberately rejected Python
verifier behavior remained Python-controlled. No report changed emitted LLVM,
native binary behavior, stdout, stderr, or exit status.

## Determinism and request stability

Five repetitions each were run for:

- single function: `lowered-add`;
- multiple functions: `multiple-functions`;
- multi-block CFG: `lowered-if-else`;
- nested aggregate/lifecycle: `struct-default-init-destroy` and
  `lifecycle-operations`;
- documented diagnostic divergence: `undefined-slot`;
- documented outcome divergence: `non-void-path-without-return`; and
- rejected structure: `missing-entry-block`.

All 40 canonical payloads were byte-identical within their case, all hashes
were identical, and all timing-free semantic snapshots were identical.
Diagnostic prose, timings, and process metadata did not affect identity.

The subprocess determinism test rebuilds a multi-function loop module in five
separate Python processes with `PYTHONHASHSEED` values `0`, `1`, `17`,
`12345`, and `random`; all emitted the same SHA-256. Canonical JSON sorts
mapping keys. Function, block, instruction, parameter, struct, field, enum
variant, and operand order intentionally remain request-significant. No
filesystem path, object/process ID, locale, environment value, set iteration,
or pass-order nondeterminism was found.

## Failure injection and authority

Focused tests cover:

| Failure | Result |
| --- | --- |
| missing executable and spawn failure | integration report; Python result unchanged |
| timeout | bounded termination; Python result unchanged |
| stdout and stderr limits | bounded termination; Python result unchanged |
| nonzero exit | untrusted stdout rejected; Python result unchanged |
| malformed/duplicate/extra JSON | integration report; Python result unchanged |
| unsupported protocol/schema and all protocol error kinds | typed infrastructure report; Python result unchanged |
| request construction failure | integration report without request hash; Python result unchanged |
| non-strict sink exception | ignored; Python result unchanged |
| strict sink exception | exposed only after Python acceptance; Python rejection still wins |

For an accepted CLI IR program, disabled mode and a shadow run with a missing
Rust executable were byte-for-byte equal: stdout `unchanged\n`, empty stderr,
and exit code 0. For rejected modules, enabled and disabled backends retain the
same rendered Python diagnostic, normalized failure, cause type, and exit
behavior. Existing CLI/native golden output assertions supply broader
equivalence evidence.

## Timing and duplication

Full-suite local shadow timing:

| Component | Median | p90 | p95 | Maximum | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| serialization | 0.173 ms | 0.361 ms | 0.532 ms | 41.085 ms | 0.848 s |
| Rust subprocess + verification | 3.854 ms | 7.936 ms | 8.048 ms | 216.670 ms | 11.748 s |
| coordinator total | 4.048 ms | 8.313 ms | 8.586 ms | 238.916 ms | 12.646 s |

The corpus-only medians were 0.091 ms serialization, 3.772 ms Rust invocation,
and 3.937 ms total. Repeated identical requests confirm subprocess startup
dominates small modules.

The full suite made 1,675 observations from 644 distinct hashes: 1,031
observations repeated an existing request. Repetition comes from the same
program crossing multiple test layers and from repeated compilation, not from
incorrect stage deduplication. A future validation-only cache could reduce
local subprocess cost substantially, but it must never bypass or affect the
authoritative Python verifier. No cache was added.

## Security and privacy

The JSON summaries and all semantic snapshots were searched for home paths,
temporary paths, request payloads, complete IR/source, arbitrary stderr,
environment mappings, and process IDs. No sensitive value was present.

Reports contain only allowed hashes, protocol/schema versions, client kind,
stage, classification, semantic diagnostic keys, bounded normalized failure
kind/summary, and timings. Test provenance appears only for non-parity
diagnosis; the final summary has no non-parity rows. Repository-relative test
names never enter `ShadowVerificationReport`.

## Known unrelated failures and limitations

The same four V1 example-manifest failures remain and were not changed:

1. the manifest omits `examples/LeetCode/isPalindrome.ae` and `twoSum.ae`;
2. `Sorts/Main.ae` has a stale capability expectation;
3. `nonlinear_systems/newton_system.ae` has stale module/function-value
   capability expectations; and
4. its AST stdout SHA-256 is stale.

They reproduce without shadow and are unrelated to the Rust verifier.

Remaining gaps before an authority proposal:

- the reviewed IRV-024 outcome divergence still exists;
- 37 invariant catalog entries are absent from corpus `covers`;
- only a small number of rejection paths occur naturally in normal compiler
  pipelines;
- Python normalized failures still omit Rust's structural context;
- classes/interfaces and 23 AST-only examples do not reach Initial IR;
- Initial IR has no CFG simplification pass to validate;
- validation is local and short-lived rather than a sustained multi-platform
  soak; and
- ordinary compilation intentionally has no packaged/selected Rust verifier.

## Validation command results

| Command | Result |
| --- | --- |
| `cargo fmt --all --check` | passed |
| `cargo check --workspace` | passed |
| `cargo test --workspace` | passed |
| `cargo clippy --workspace --all-targets --all-features -- -D warnings` | passed |
| focused coordinator/client/adapter/corpus/determinism/failure tests | 94 passed |
| focused optimizer/module/import/native/example/benchmark tests | 249 passed, 1 skipped |
| full pytest with explicit shadow injection | 4,194 passed, 1 skipped, 4 unchanged known V1 failures |
| `git diff --check` | passed |

## Readiness criteria

| Criterion | Result after the narrow fix |
| --- | ---: |
| unexpected outcome divergences | 0 |
| unexpected diagnostic divergences | 0 |
| valid-run Rust infrastructure failures | 0 |
| valid-run Rust integration failures | 0 |
| canonical request nondeterminism | 0 |
| semantic report nondeterminism | 0 |
| compiler output changes caused by shadow | 0 |
| compiler exit-code changes caused by shadow | 0 |
| unclassified transportable corpus cases | 0 |

Phase 4.4 therefore passes its immediate observational criteria. Phase 4.5
should not yet make Rust authoritative: first resolve or deliberately retain
IRV-024 with an authority policy, enrich Python structural context or define a
reviewed equivalence contract, close priority invariant/feature gaps, and
collect longer multi-platform real-program evidence.
