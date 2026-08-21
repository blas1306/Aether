//! Canonical RUST-1.1 mappings for checks shared by a Rust verifier phase.
//!
//! This is evidence metadata, not verifier control flow. It makes semantic
//! mappings derivable without duplicating otherwise equivalent checks.

/// Direct evidence for every rule reported as missing by RUST-1.
pub const RUST_1_1_PARITY_MAPPINGS: &[(&str, &str, &str)] = &[
    (
        "IRV-012",
        "TypeVerifier::require_valid_type",
        "type_verifier",
    ),
    (
        "IRV-013",
        "TypeVerifier::require_valid_type",
        "type_verifier",
    ),
    (
        "IRV-014",
        "TypeVerifier::require_valid_type",
        "type_verifier",
    ),
    (
        "IRV-015",
        "TypeVerifier::require_valid_type",
        "type_verifier",
    ),
    (
        "IRV-023",
        "IRInstruction exhaustive dispatch",
        "type_verifier",
    ),
    (
        "IRV-031",
        "SSA/lifecycle name resolution",
        "lifecycle_verifier",
    ),
    (
        "IRV-035",
        "dominance and lifecycle predecessor intersection",
        "dominance_verifier",
    ),
    (
        "IRV-036",
        "lifecycle predecessor-state join",
        "lifecycle_dataflow_verifier",
    ),
    (
        "IRV-054",
        "SSA operands before builtin validation",
        "builtin_verifier",
    ),
    ("IRV-131", "handler entry shape", "exception_verifier"),
    (
        "IRV-132",
        "catch event type validation",
        "exception_verifier",
    ),
    (
        "IRV-133",
        "handler identity validation",
        "exception_verifier",
    ),
    ("IRV-134", "catch metadata uniqueness", "exception_verifier"),
    ("IRV-135", "root catch ordering", "exception_verifier"),
    (
        "IRV-137",
        "invoke exception event type",
        "exception_verifier",
    ),
    (
        "IRV-138",
        "invoke handler event edge binding",
        "exception_verifier",
    ),
    (
        "IRV-139",
        "exceptional transfer event type",
        "exception_verifier",
    ),
    (
        "IRV-140",
        "exceptional target/event pairing",
        "exception_verifier",
    ),
    (
        "IRV-141",
        "exceptional handler event binding",
        "exception_verifier",
    ),
    (
        "IRV-142",
        "handler exceptional reachability",
        "exception_verifier",
    ),
    ("IRV-143", "handler predecessor kind", "exception_verifier"),
    ("IRV-144", "function exception effect", "exception_verifier"),
    ("IRV-145", "throwing call must invoke", "exception_verifier"),
    (
        "IRV-146",
        "invoke requires throwing target",
        "exception_verifier",
    ),
    (
        "IRV-147",
        "rethrow active-handler provenance",
        "exception_verifier",
    ),
    (
        "IRV-148",
        "exception event linear consumption",
        "exception_verifier",
    ),
];

#[cfg(test)]
mod tests {
    use super::RUST_1_1_PARITY_MAPPINGS;
    use std::collections::HashSet;

    #[test]
    fn closure_registry_has_the_frozen_twenty_six_unique_rules() {
        let ids = RUST_1_1_PARITY_MAPPINGS
            .iter()
            .map(|(id, _, _)| *id)
            .collect::<HashSet<_>>();
        assert_eq!(RUST_1_1_PARITY_MAPPINGS.len(), 26);
        assert_eq!(ids.len(), 26);
    }
}
