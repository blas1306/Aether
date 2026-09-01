# RUST-IR-2 — cierre de qualification PRE-lifecycle shadow

## Decisión

`RUST_INITIAL_IR_PRE_LIFECYCLE_SHADOW_QUALIFIED`

Esta decisión corresponde exclusivamente al run oficial nuevo [33465504645](https://github.com/blas1306/Aether/actions/runs/33465504645), ejecutado por `workflow_dispatch` sobre `main` en la revisión exacta `bd156a52757721fba552231fa88ac7083b715b6d`. El run terminó `success` el 1 de septiembre de 2026 y, además, pasó el checker fail-closed oficial y una recomposición independiente. El éxito visual de GitHub no fue usado como sustituto de esos gates.

La base productiva RUST-IR-1 permanece en `b563054f5f94ab373089f4d9dd9ae7629f242a59`. Este cierre no promueve Rust Initial IR authority, no retira Python IRVerifier, no modifica LifecycleExpander y no inicia RUST-IR-3.

## Identidad y runs históricos

Los dos intentos anteriores se preservan permanentemente y no aportaron artifacts al run calificado:

| Run | Revisión | Estado preservado | Reutilización |
|---|---|---|---|
| `33462871203` | `630ff5fdbd2ee21a67f0018c9392e8d4d9330e8b` | `FAILED/BLOCKED` | ninguna |
| `33464649897` | `1acc48bae5aa8ed5366c1647613b48929caddcff` | `FAILED/BLOCKED` | ninguna |
| `33465504645` | `bd156a52757721fba552231fa88ac7083b715b6d` | `SUCCESS/QUALIFIED` | sólo artifacts propios |

`origin/main`, el tracking ref local y la API de GitHub fueron verificados contra la revisión exacta calificada antes de disparar el tercer run.

## Jobs obligatorios

Los 21 jobs terminaron en `success`: contract-and-baseline, rust-verifier-unit, valid-corpus-differential, mutation-campaign, critical-irv041-regressions, production-pre-lifecycle-provenance, lifecycle-boundary-regression, packaged-clean-consumer, source-development-install, next-request-recovery, transport-continuity, performance-characterization, las cuatro plataformas, las cuatro versiones de CPython y aggregate-fail-closed. Sus IDs exactos están sellados en el registro JSON de cierre.

## Artifacts y hashes

Se descargaron nuevamente y de forma independiente todos los artifacts del run `33465504645`. Para los 20 producer artifacts coincidieron nombre, ID, source job, run, revisión, role, kind, estado, digest de GitHub, SHA-256 del ZIP y SHA-256 de la evidencia extraída. El aggregate fue el artifact número 21.

| Artifact | ID | ZIP/GitHub SHA-256 | Evidence SHA-256 |
|---|---:|---|---|
| rust-ir-2-contract | `9784685066` | `1bb2ff8861cc609876c158d8f20ad59fc3feefb64e9f9f6e614aeafdcd308e20` | `aa1e4cc144506616777e94abe5a3b54ab1da24d41f8222116e158fe94dc61191` |
| rust-ir-2-rust-validation | `9784723914` | `1c62a60be33b704a99ce3e2223f52c55b7827af77d7319027eebe249b0969342` | `6b4543dc65f22da29d054f0394d781206fc246054a1e28477f36fdf323ad8c39` |
| rust-ir-2-valid-corpus | `9784747561` | `0fb632b02a8ff41e2d083b0e708e3efb46d2e0868cd4fb8a46ed2316ae6b09ba` | `b0df6fb4b075523f77355903e73d0c2d8b4f03ec3e77f5d4c22987cdcfa9df67` |
| rust-ir-2-mutations | `9784744946` | `60611eb90fc9d928902e477fb8a99cd40bcdadd12251f2d38c090ded216f5192` | `98b25c38a236a841aa245636b427126f1346a682862293dd6df231565e1a0d3a` |
| rust-ir-2-irv041 | `9784700749` | `650251cf83d4bd2c058c735b19a02722898b3c6de0347f9c669c51a966c64197` | `3df92ff88d6b55e0166fbd3bd3d914b4973ad6c3d7fd0528ff5672cd4dee8b8e` |
| rust-ir-2-provenance | `9784732096` | `59d4390b606016f9490f8ca547e9c96ac99a1b5f89e30e320153c302be37a7fd` | `da883010c5693ca0150c2694397e2ecf9f71dba09e2e0c480f4498ba5c550c85` |
| rust-ir-2-lifecycle-boundary | `9784742405` | `8d056170cd5c649877549a69c02bedea34aa9b73cad726c7b4efee7d5d2d7bd1` | `ae017eead1e9d046b62e81c4ad1d7d668d334e8ae5b74aeddd906368ebf63753` |
| rust-ir-2-packaged-consumer | `9784740884` | `d7f7910d1da1b28eef51a98a838d0f60947603abb9b6c4e4c80c92198da8d8f3` | `3f8750ba53e4c76d7f122214b5d960a6d762023623b2decbb325136f1ed373f5` |
| rust-ir-2-source-install | `9784827518` | `1438e8bbc7ecb70ad5c5f2b4c88cdc1526843a34e9e8941463acb1fc4cf06208` | `07ed79ff463aa2c581ba01506121b4ae9557000909d223143af793ce15ded208` |
| rust-ir-2-recovery | `9784740654` | `a79be026f360a00a570704337abf4a2c93cbbee8fb77a549a05a93dabdd2a4cb` | `f241d4294c2314bd69e1a72c2a8d4211dddaebf0867e5fe9de5a3d08014fb581` |
| rust-ir-2-transport | `9784741855` | `bb66957da35e09c1a9be02381ddb0a345c05508d19fec1d2214a9f9f5f59dc40` | `0ab7ddfe1fe7cc5739dd8e084fc8c21bea0dc99a37c285d21f662c9b6b5c7830` |
| rust-ir-2-performance | `9784703136` | `a79b4269c5ddfb40523b4e842265d04a7e0fa50bfea3d67a5e09412d301e4671` | `8f54aa0086297fb8f72f225cdb5abce96b668f0e3f926da5a44ad87f23474f65` |
| rust-ir-2-platform-linux-x86_64 | `9784741409` | `fd725bc91cea5814d4edefe6dbf2e41a0f0aadbaf15e3fe4da38b60edbfdb715` | `6eaaf1855f4172f94f3f48f7b93adcdd2219f986a9cdeebeb30d8ca3161c877d` |
| rust-ir-2-platform-windows-x86_64 | `9784803370` | `1e8cfd66f9dfb13f28239fcdf0eaa00721fd9d078c58be6254c309549e297645` | `e644c88a4fe1b2f87755058fc161857425290d5f2da0eec2c0e4775abe2d1b7e` |
| rust-ir-2-platform-macos-x86_64 | `9784867564` | `42b8c67458b6da8aa8be447d99c7d17c5ad18847948e1460ab347f9cb24aced2` | `833d40ee60a8ce1c6bef01b82ef9577b49591c7fca35310f0fedc8bd7396ba51` |
| rust-ir-2-platform-macos-arm64 | `9784762193` | `ae42eb5aa2df75d680c0ca7e572f30a297bf319fee451b62f0f3e3e55871ff5f` | `e96e95e903023fe48bcc163e03168dd2f6b87120dd62fb54146c8dd229c8ae11` |
| rust-ir-2-python-3.11 | `9784740416` | `cd9639aa7853d720826d299dd938ca1948a4dbb59c1d2bcf1ba4eeb65820b333` | `000ae06ee9a91c7173d176c09d721ee27a6dda3f57c5b48da647ab751031c5ab` |
| rust-ir-2-python-3.12 | `9784743563` | `55b362ff5ae61fca37dadf93ecbf2e575ec04c61f414474669c0e13398fe6b4d` | `a8894f3b9f58cb4c4b8ebe81612d7dc8eb0cc79d0beee1844132c9681462727f` |
| rust-ir-2-python-3.13 | `9784743587` | `d007665e3073d962879a545ab76294a7d7bc26441ef98446d5470714cd33c0e0` | `a4a1bc03672cada5f6f69a8d011281fadc547a68a6a4010330e99eb7c485b86a` |
| rust-ir-2-python-3.14 | `9784744078` | `1f2e9a73c2b9e10565dfe7e8453d67cafa0c6e7fe9f73baa3f354ffb13c68dd2` | `38f87eabc5ae9b99a4e013570e3a1198166ff8f66eccd64d7298910e96698df8` |
| rust-ir-2-aggregate | `9784875877` | `3cb149b90d3a657e09136cd2e17ff817f3e4db616b311ba80be237e10709c281` | decision: `458cc9f371ee470c414eafc94b911308282fdf6a4488280e8300e3a9ff218f7a` |

El manifest oficial y el recompuesto son byte a byte idénticos: `3984605a7a81377e74012a17717b0c1a82f17f27ee800b7ee5dfec02cd1a1b77`. Las decisiones también son idénticas: `458cc9f371ee470c414eafc94b911308282fdf6a4488280e8300e3a9ff218f7a`. El checker oficial usado para el replay tiene SHA-256 `80b5e45efb269e552c1d821cf77ebb0dec8102ee5e6cac59636095ca8397ba32`.

## Evidencia de comportamiento

El probe de producción observó, en orden, `python_ir_verifier_pass`, `rust_verify_module_executed`, `rust_verify_module_pass` y `python_lifecycle_expander_executed`. El hash de request observado y el recompuesto coincidieron, el mismo objeto llegó a LifecycleExpander y no apareció un gate Rust productivo post-lifecycle.

Los dos casos críticos IRV-041 fueron aceptados por Python y Rust PRE-lifecycle. Su rechazo post-lifecycle sólo se observó en una sonda de qualification y no constituye authority productiva. El corpus válido cubrió 65 casos, y la campaña cubrió 75 mutaciones requeridas, 77 casos totales y 17 familias. Hubo cero acceptance divergences en ambos conjuntos.

El clean packaged consumer descubrió `aether-ir-verifier` desde la distribución instalada, mantuvo el descubrimiento al cambiar el directorio de trabajo y operó sin checkout, Cargo ni rustc. Pasó valid→invalid→valid y compilación completa. El source/development install construyó dentro de su propio job todos los componentes requeridos, incluido `verify_owned_ssa_refinement`, sin copiar binarios desde otros artifacts o directorios `target/`; luego pasó valid→invalid→valid, compilación completa y la suite (`5260 passed`, `12 skipped`).

Las plataformas linux-x86_64, windows-x86_64, macos-x86_64 y macos-arm64 pasaron como consumidores limpios. También pasaron CPython 3.11.16, 3.12.14, 3.13.15 y 3.14.7. Los transports in-process y companion pasaron sin fallback; el IR verifier continuó siendo un subprocess independiente. La recuperación persistente produjo accept→reject→accept sin contaminación.

Rust fmt y tests pasaron. El delta clippy propio fue limpio con cero findings actuales; no se formula una afirmación de clippy global. La caracterización de performance quedó muy por debajo del umbral de patología de 1000 ms y no activó un gate correctivo.

Los 24 fallos locales de LeakSanitizer bajo ptrace no se reinterpretaron como PASS ni se ignoraron: no se reprodujeron en el entorno oficial. El log source oficial contiene cero incidencias LeakSanitizer/ptrace.

## Alcance de authority

La authority de Initial IR sigue siendo `Python IRVerifier AND Rust verify_module` en shadow PRE-lifecycle. LifecycleExpander sigue siendo Python y ocurre después de ambos gates de Initial IR. SSA refinement se preserva. Este resultado no autoriza promoción exclusiva de Rust, retiro del verificador Python, cambios a LifecycleExpander ni trabajo de RUST-IR-3.

El registro machine-readable es `docs/compiler/rust_ir_2_pre_lifecycle_shadow_qualification_closure_bd156a5.json`. Su checker fail-closed es `scripts/check_rust_ir_2_pre_lifecycle_shadow_qualification_closure_bd156a5.py`.
