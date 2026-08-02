# Aether documentation status

This index prevents design history and audit snapshots from being mistaken for
the release contract.

## Normative

- [Aether 1.0 Language Specification](AETHER_LANGUAGE_SPEC_V1.md)
- [Aether Native Profile v1](AETHER_NATIVE_PROFILE_V1.md)
- [Aether 1.0.0-rc.4 release notes](AETHER_1_0_0_RC4_RELEASE_NOTES.md)

The language specification and native profile define the current Aether 1.0
contract for the `1.0.0-rc.4` candidate. Frontend or AST acceptance does not
widen it. The ALPT1
byte contract in
[Persistence Format Design](PERSISTENCE_FORMAT_DESIGN.md) remains normative for
that format only; it is not a second language specification.

The [native profile](AETHER_NATIVE_PROFILE_V1.md) is the executable capability
refinement. The [profile audit](AETHER_V1_PROFILE_AUDIT.md) and
[closed decision](AETHER_V1_PROFILE_DECISION.md) are historical profile-22
closure evidence; they do not override profile 23. The reproducible example
classification is in the
[v1 examples manifest](../../examples/v1_examples_manifest.json), with the
four formerly broken cases resolved in the
[RC3 catalog audit](AETHER_EXAMPLES_CATALOG_AUDIT.md), retained as a dated
audit.

## Design / RFC

- [Aether v1 Scope](AETHER_V1_SCOPE.md)
- [Backend Capability Profiles](BACKEND_CAPABILITY_PROFILES.md)
- [Builtins and Stdlib Design](BUILTINS_AND_STDLIB_DESIGN.md)
- [String Runtime Design](STRING_RUNTIME_DESIGN.md)
- [Collection Runtime Design](COLLECTION_RUNTIME_DESIGN.md)
- [Value Lifecycle Design](../compiler/VALUE_LIFECYCLE_DESIGN.md)
- [Text File IO Design](TEXT_FILE_IO_DESIGN.md)
- [Persistence Format Design / ALPT1](PERSISTENCE_FORMAT_DESIGN.md)
- [Aether frontend experiments outside 1.0](AETHER_FRONTEND_EXPERIMENTS.md)
- [Aether IR initial design](AETHER_IR_DESIGN.md)

Design/RFC documents may contain implementation history, rejected alternatives
or future work. They do not expand the release profile.

## Historical

- [Aether v0 Specification](AETHER_V0_SPEC.md)
- [Evolution](../EVOLUTION.md)

## Audit

- [Final Aether v1 Profile Audit](AETHER_V1_PROFILE_AUDIT.md)
- [Aether v1 Profile Decision](AETHER_V1_PROFILE_DECISION.md)
- [Aether v1 Closure Roadmap](AETHER_V1_CLOSURE_ROADMAP.md)
- [Public diagnostics contract](AETHER_DIAGNOSTICS.md)
- [RC3 Examples Catalog Audit](AETHER_EXAMPLES_CATALOG_AUDIT.md)
- [Aether v1 Release Readiness](AETHER_V1_RELEASE_READINESS.md)
- [Backend Feature Parity](BACKEND_FEATURE_PARITY.md)
- [Exception Release Qualification](../compiler/EXCEPTION_RELEASE_QUALIFICATION.md)
- [Control Flow and Iteration Audit](CONTROL_FLOW_AND_ITERATION_AUDIT.md)

Audit documents are dated snapshots. A closed finding remains useful history
but is not a normative language rule.
