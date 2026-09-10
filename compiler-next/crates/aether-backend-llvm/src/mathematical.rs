//! Physical helpers shared by the closed mathematical emitters.
//! Caller has already verified descriptor selectors, bounds and schedule.
use aether_middle::{MathAxis, MathInput, MathStride};
use std::fmt::Write;

/// Emit exactly `i*stride` or `r*row_stride+c*column_stride` followed by a load.
/// Source layout is never inferred from result layout or orientation.
pub(super) fn emit_strided_load(
    output: &mut String,
    prefix: &str,
    element: &str,
    input: MathInput,
    offset: &[(MathAxis, MathStride)],
) {
    let mut terms = Vec::new();
    for (axis, stride) in offset {
        let term = format!("%{prefix}_{input:?}_{axis:?}_offset");
        writeln!(
            output,
            "  {term} = mul i64 %{prefix}_{axis:?}_index, %{prefix}_{input:?}_{stride:?}"
        )
        .unwrap();
        terms.push(term);
    }
    let offset = if terms.len() == 1 {
        terms[0].clone()
    } else {
        writeln!(
            output,
            "  %{prefix}_{input:?}_offset = add i64 {}, {}",
            terms[0], terms[1]
        )
        .unwrap();
        format!("%{prefix}_{input:?}_offset")
    };
    writeln!(output, "  %{prefix}_{input:?}_slot = getelementptr {element}, ptr %{prefix}_{input:?}_ptr, i64 {offset}\n  %{prefix}_{input:?}_value = load {element}, ptr %{prefix}_{input:?}_slot").unwrap();
}

/// Set both immutable Matrix shape fields on an existing pointer descriptor.
/// For an empty owner base is zeroinitializer (null pointer); both axes MUST
/// still be inserted. Allocation helpers use the same construction after their
/// null/allocated pointer phi. This function emits no calls or guards.
pub(super) fn emit_matrix_shape(
    output: &mut String,
    base: &str,
    rows: &str,
    columns: &str,
    names: [&str; 2],
) {
    let [row_shape, owner] = names;
    writeln!(output, "  {row_shape} = insertvalue {{ ptr, i64, i64 }} {base}, i64 {rows}, 1\n  {owner} = insertvalue {{ ptr, i64, i64 }} {row_shape}, i64 {columns}, 2").unwrap();
}
