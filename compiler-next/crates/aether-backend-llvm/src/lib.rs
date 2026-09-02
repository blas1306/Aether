//! LLVM backend for verified Vertical-10 program SSA.

use std::collections::BTreeSet;
use std::fmt::Write;

use aether_frontend::{
    CastKind, CoercionKind, EnumInfo, FieldId, FloatType, FloatValue, FunctionInstanceInfo,
    IntegerType, ModuleInfo, StructInfo, Substitution, TargetProperties, TypeArena, TypeData,
    TypeId, layout_of,
};
use aether_middle::{
    BinaryOp, BlockId, SsaFunction, SsaOp, SsaOperand, SsaPlace, SsaPlaceBase, SsaPlaceProjection,
    SsaTerminator, TrapKind, UnaryOp, VerifiedSsa,
};

/// Minimal explicit target contract for the admitted bootstrap platform.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TargetDescriptor {
    /// LLVM target triple.
    pub triple: &'static str,
    /// Semantic/layout properties shared with type analysis.
    pub properties: TargetProperties,
}

impl TargetDescriptor {
    /// The target admitted through NEXT-VERTICAL-10.
    #[must_use]
    pub const fn linux_x86_64() -> Self {
        Self {
            triple: "x86_64-unknown-linux-gnu",
            properties: TargetProperties::LINUX_X86_64,
        }
    }
}

/// Backend boundary: only verified SSA can cross it.
pub trait Backend {
    /// Produces a complete backend module.
    fn emit(&self, ssa: &VerifiedSsa, target: &TargetDescriptor) -> String;
}

/// Bootstrap textual LLVM backend.
#[derive(Clone, Copy, Debug, Default)]
pub struct LlvmTextBackend;

impl Backend for LlvmTextBackend {
    fn emit(&self, ssa: &VerifiedSsa, target: &TargetDescriptor) -> String {
        emit_llvm(ssa, target)
    }
}

/// Lowers verified program SSA to deterministic textual LLVM IR.
#[must_use]
#[allow(clippy::too_many_lines)]
pub fn emit_llvm(ssa: &VerifiedSsa, target: &TargetDescriptor) -> String {
    let program = ssa.as_ssa();
    let types = &program.types;
    let buffer_elements = types
        .entries()
        .filter_map(|(ty, data)| match data {
            TypeData::Buffer { element } if !types.contains_generic(ty) => Some(*element),
            _ => None,
        })
        .collect::<BTreeSet<_>>();
    let indexed_elements = types
        .entries()
        .filter_map(|(ty, data)| match data {
            TypeData::Buffer { element } | TypeData::View { element, .. }
                if !types.contains_generic(ty) =>
            {
                Some(*element)
            }
            _ => None,
        })
        .collect::<BTreeSet<_>>();
    let has_buffers = !buffer_elements.is_empty();
    let mut output = String::new();
    writeln!(output, "; Aether NEXT-VERTICAL-10").unwrap();
    writeln!(
        output,
        "; Internal bootstrap ABI and symbol mangling; not a public Aether ABI"
    )
    .unwrap();

    writeln!(output, "target triple = \"{}\"\n", target.triple).unwrap();
    for bits in [8, 16, 32, 64] {
        for family in ['s', 'u'] {
            for op in ["add", "sub", "mul"] {
                writeln!(output,"declare {{ i{bits}, i1 }} @llvm.{family}{op}.with.overflow.i{bits}(i{bits}, i{bits})").unwrap();
            }
        }
    }
    writeln!(output, "declare void @llvm.trap() cold noreturn nounwind\n").unwrap();
    if has_buffers {
        emit_runtime_boundary(&mut output);
    }

    for (ty, data) in types.entries() {
        if types.contains_generic(ty) {
            continue;
        }
        let id = match data {
            TypeData::Struct(id)
                if program.structs[id.0 as usize].generic_parameters.is_empty() =>
            {
                *id
            }
            TypeData::StructInstance(id, _) => *id,
            _ => continue,
        };
        let info = &program.structs[id.0 as usize];
        let fields = info
            .fields
            .iter()
            .map(|field| {
                llvm_type(
                    types,
                    concrete_struct_member(types, &program.structs, ty, field.ty),
                )
            })
            .collect::<Vec<_>>()
            .join(", ");
        writeln!(output, "{} = type {{ {fields} }}", llvm_type(types, ty)).unwrap();
    }
    for (ty, data) in types.entries() {
        if types.contains_generic(ty) {
            continue;
        }
        let id = match data {
            TypeData::Enum(id) if program.enums[id.0 as usize].generic_parameters.is_empty() => *id,
            TypeData::EnumInstance(id, _) => *id,
            _ => continue,
        };
        let info = &program.enums[id.0 as usize];
        let mut fields = vec!["i32".to_string()];
        fields.extend(info.variants.iter().map(|variant| {
            let payloads = variant
                .payloads
                .iter()
                .map(|payload| {
                    llvm_type(
                        types,
                        concrete_enum_member(types, &program.enums, ty, payload.ty),
                    )
                })
                .collect::<Vec<_>>()
                .join(", ");
            format!("{{ {payloads} }}")
        }));
        writeln!(
            output,
            "{} = type {{ {} }}",
            llvm_type(types, ty),
            fields.join(", ")
        )
        .unwrap();
    }
    if !program.structs.is_empty() || !program.enums.is_empty() {
        writeln!(output).unwrap();
    }
    for element in buffer_elements {
        let layout = layout_of(
            types,
            element,
            target.properties,
            &program.structs,
            &program.enums,
        )
        .expect("verified Buffer element has concrete layout");
        emit_buffer_allocation_helper(&mut output, types, element, layout.size, layout.align);
    }
    for element in indexed_elements {
        emit_index_helper(&mut output, types, element);
    }

    for function in &program.functions {
        let signature = &program.signatures[function.id.0 as usize];
        emit_function(
            &mut output,
            function,
            signature,
            &program.signatures,
            &program.modules,
            &program.structs,
            &program.enums,
            types,
        );
    }

    let entry = &program.signatures[program.entry.0 as usize];
    writeln!(output, "define i32 @main() {{").unwrap();
    writeln!(output, "entry:").unwrap();
    writeln!(
        output,
        "  %aether_result = call i64 @{}()",
        bootstrap_symbol(
            entry,
            &program.modules,
            &program.structs,
            &program.enums,
            types
        )
    )
    .unwrap();
    writeln!(
        output,
        "  %process_status = trunc i64 %aether_result to i32"
    )
    .unwrap();
    if has_buffers {
        writeln!(
            output,
            "  %allocation_balance = call i64 @aether_allocation_balance()"
        )
        .unwrap();
        writeln!(
            output,
            "  %allocation_balanced = icmp eq i64 %allocation_balance, 0"
        )
        .unwrap();
        writeln!(
            output,
            "  br i1 %allocation_balanced, label %return, label %trap_lifecycle_invariant"
        )
        .unwrap();
        writeln!(output, "return:").unwrap();
        writeln!(output, "  ret i32 %process_status").unwrap();
        writeln!(output, "trap_lifecycle_invariant:").unwrap();
        writeln!(output, "  call void @llvm.trap()").unwrap();
        writeln!(output, "  unreachable").unwrap();
    } else {
        writeln!(output, "  ret i32 %process_status").unwrap();
    }
    writeln!(output, "}}").unwrap();
    output
}

fn emit_runtime_boundary(output: &mut String) {
    output.push_str(
        "@aether_heap_alloc_count = internal global i64 0\n\
         @aether_heap_free_count = internal global i64 0\n\
         declare ptr @malloc(i64)\n\
         declare void @free(ptr)\n\
         define internal ptr @aether_alloc(i64 %size, i64 %align) {\n\
         entry:\n\
           %alloc_zero = icmp eq i64 %size, 0\n\
           %alloc_actual = select i1 %alloc_zero, i64 1, i64 %size\n\
           %alloc_ptr = call ptr @malloc(i64 %alloc_actual)\n\
           %alloc_failed = icmp eq ptr %alloc_ptr, null\n\
           br i1 %alloc_failed, label %trap_allocation_failure, label %alloc_success\n\
         alloc_success:\n\
           %alloc_count = load i64, ptr @aether_heap_alloc_count\n\
           %alloc_next = add i64 %alloc_count, 1\n\
           store i64 %alloc_next, ptr @aether_heap_alloc_count\n\
           ret ptr %alloc_ptr\n\
         trap_allocation_failure:\n\
           ; structured Aether trap: AllocationFailure\n\
           call void @llvm.trap()\n\
           unreachable\n\
         }\n\
         define internal void @aether_free(ptr %ptr, i64 %size, i64 %align) {\n\
         entry:\n\
           %free_count = load i64, ptr @aether_heap_free_count\n\
           %free_next = add i64 %free_count, 1\n\
           store i64 %free_next, ptr @aether_heap_free_count\n\
           call void @free(ptr %ptr)\n\
           ret void\n\
         }\n\
         define internal i64 @aether_allocation_balance() {\n\
         entry:\n\
           %balance_allocs = load i64, ptr @aether_heap_alloc_count\n\
           %balance_frees = load i64, ptr @aether_heap_free_count\n\
           %balance = sub i64 %balance_allocs, %balance_frees\n\
           ret i64 %balance\n\
         }\n\n",
    );
}

fn emit_buffer_allocation_helper(
    output: &mut String,
    types: &TypeArena,
    element: TypeId,
    element_size: u64,
    element_align: u64,
) {
    let suffix = mangle_type(types, element);
    let element_ty = llvm_type(types, element);
    writeln!(
        output,
        "define internal {{ ptr, i64 }} @aether_buffer_new_{suffix}(i64 %length, {element_ty} %initial) {{"
    )
    .unwrap();
    writeln!(output, "entry:").unwrap();
    writeln!(
        output,
        "  %size_checked = call {{ i64, i1 }} @llvm.umul.with.overflow.i64(i64 %length, i64 {element_size})"
    )
    .unwrap();
    writeln!(
        output,
        "  %size = extractvalue {{ i64, i1 }} %size_checked, 0"
    )
    .unwrap();
    writeln!(
        output,
        "  %size_overflow = extractvalue {{ i64, i1 }} %size_checked, 1"
    )
    .unwrap();
    writeln!(
        output,
        "  br i1 %size_overflow, label %trap_allocation_size_overflow, label %allocate"
    )
    .unwrap();
    writeln!(output, "allocate:").unwrap();
    writeln!(
        output,
        "  %data = call ptr @aether_alloc(i64 %size, i64 {element_align})"
    )
    .unwrap();
    writeln!(output, "  br label %fill_header").unwrap();
    writeln!(output, "fill_header:").unwrap();
    writeln!(
        output,
        "  %index = phi i64 [ 0, %allocate ], [ %next, %fill_body ]"
    )
    .unwrap();
    writeln!(output, "  %more = icmp ult i64 %index, %length").unwrap();
    writeln!(output, "  br i1 %more, label %fill_body, label %done").unwrap();
    writeln!(output, "fill_body:").unwrap();
    writeln!(
        output,
        "  %slot = getelementptr inbounds {element_ty}, ptr %data, i64 %index"
    )
    .unwrap();
    writeln!(output, "  store {element_ty} %initial, ptr %slot").unwrap();
    writeln!(output, "  %next = add i64 %index, 1").unwrap();
    writeln!(output, "  br label %fill_header").unwrap();
    writeln!(output, "done:").unwrap();
    writeln!(
        output,
        "  %descriptor_data = insertvalue {{ ptr, i64 }} poison, ptr %data, 0"
    )
    .unwrap();
    writeln!(
        output,
        "  %descriptor = insertvalue {{ ptr, i64 }} %descriptor_data, i64 %length, 1"
    )
    .unwrap();
    writeln!(output, "  ret {{ ptr, i64 }} %descriptor").unwrap();
    writeln!(output, "trap_allocation_size_overflow:").unwrap();
    writeln!(output, "  ; structured Aether trap: AllocationSizeOverflow").unwrap();
    writeln!(output, "  call void @llvm.trap()").unwrap();
    writeln!(output, "  unreachable\n}}\n").unwrap();
}

fn emit_index_helper(output: &mut String, types: &TypeArena, element: TypeId) {
    let suffix = mangle_type(types, element);
    let element_ty = llvm_type(types, element);
    writeln!(
        output,
        "define internal ptr @aether_index_{suffix}({{ ptr, i64 }} %descriptor, i64 %index) {{"
    )
    .unwrap();
    writeln!(output, "entry:").unwrap();
    writeln!(
        output,
        "  %length = extractvalue {{ ptr, i64 }} %descriptor, 1"
    )
    .unwrap();
    writeln!(output, "  %in_bounds = icmp ult i64 %index, %length").unwrap();
    writeln!(
        output,
        "  br i1 %in_bounds, label %valid, label %trap_index_out_of_bounds"
    )
    .unwrap();
    writeln!(output, "valid:").unwrap();
    writeln!(
        output,
        "  %data = extractvalue {{ ptr, i64 }} %descriptor, 0"
    )
    .unwrap();
    writeln!(
        output,
        "  %element = getelementptr inbounds {element_ty}, ptr %data, i64 %index"
    )
    .unwrap();
    writeln!(output, "  ret ptr %element").unwrap();
    writeln!(output, "trap_index_out_of_bounds:").unwrap();
    writeln!(output, "  ; structured Aether trap: IndexOutOfBounds").unwrap();
    writeln!(output, "  call void @llvm.trap()").unwrap();
    writeln!(output, "  unreachable\n}}\n").unwrap();
}

#[allow(clippy::too_many_arguments, clippy::too_many_lines)]
fn emit_function(
    output: &mut String,
    function: &SsaFunction,
    signature: &FunctionInstanceInfo,
    signatures: &[FunctionInstanceInfo],
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
) {
    let parameters = function
        .parameters
        .iter()
        .map(|parameter| format!("{} %v{}", llvm_type(types, parameter.ty), parameter.value.0))
        .collect::<Vec<_>>()
        .join(", ");
    writeln!(
        output,
        "define {} @{}({parameters}) {{",
        llvm_type(types, signature.return_type),
        bootstrap_symbol(signature, modules, structs, enums, types)
    )
    .unwrap();

    if !function.memory_locals.is_empty() {
        writeln!(output, "entry.storage:").unwrap();
        for memory in &function.memory_locals {
            writeln!(
                output,
                "  %m{} = alloca {}",
                memory.local.0,
                llvm_type(types, memory.ty)
            )
            .unwrap();
            if let Some(parameter) = memory.parameter {
                writeln!(
                    output,
                    "  store {} %v{}, ptr %m{}",
                    llvm_type(types, memory.ty),
                    parameter.0,
                    memory.local.0
                )
                .unwrap();
            }
        }
        writeln!(output, "  br label %{}", block_label(function.entry)).unwrap();
    }

    let exit_labels: Vec<String> = function
        .blocks
        .iter()
        .map(|block| {
            block
                .instructions
                .iter()
                .rev()
                .find(|instruction| is_checked(&instruction.op))
                .map_or_else(
                    || block_label(block.id),
                    |instruction| continuation_label(block.id, instruction.result.0),
                )
        })
        .collect();
    let mut overflow_trap = false;
    let mut division_trap = false;
    let mut conversion_trap = false;
    let mut division_overflow_trap = false;
    let mut allocation_size_trap = false;
    let mut allocation_failure_trap = false;
    let mut bounds_trap = false;
    for block in &function.blocks {
        writeln!(output, "{}:", block_label(block.id)).unwrap();
        for phi in &block.phis {
            let incoming = phi
                .incoming
                .iter()
                .map(|(predecessor, value)| {
                    format!(
                        "[ %v{}, %{} ]",
                        value.0, exit_labels[predecessor.0 as usize]
                    )
                })
                .collect::<Vec<_>>()
                .join(", ");
            writeln!(
                output,
                "  %v{} = phi {} {}",
                phi.result.0,
                llvm_type(types, phi.ty),
                incoming
            )
            .unwrap();
        }
        for instruction in &block.instructions {
            match &instruction.op {
                SsaOp::Use(operand) => writeln!(
                    output,
                    "  %v{} = select i1 true, {} {}, {} {}",
                    instruction.result.0,
                    llvm_type(types, instruction.ty),
                    llvm_operand(operand),
                    llvm_type(types, instruction.ty),
                    llvm_operand(operand)
                )
                .unwrap(),
                SsaOp::Load { place } => {
                    let pointer = emit_place_pointer(
                        output,
                        function,
                        place,
                        instruction.result.0,
                        types,
                        structs,
                    );
                    writeln!(
                        output,
                        "  %v{} = load {}, ptr {pointer}",
                        instruction.result.0,
                        llvm_type(types, instruction.ty)
                    )
                    .unwrap();
                }
                SsaOp::Store { place, value } => {
                    let pointer = emit_place_pointer(
                        output,
                        function,
                        place,
                        instruction.result.0,
                        types,
                        structs,
                    );
                    writeln!(
                        output,
                        "  store {} {}, ptr {pointer}",
                        llvm_type(types, operand_type(function, value)),
                        llvm_operand(value)
                    )
                    .unwrap();
                    if instruction.ty == TypeId::BOOL
                        && operand_type(function, value) != TypeId::BOOL
                    {
                        writeln!(
                            output,
                            "  %v{} = select i1 true, i1 true, i1 true",
                            instruction.result.0
                        )
                        .unwrap();
                    } else {
                        writeln!(
                            output,
                            "  %v{} = select i1 true, {} {}, {} {}",
                            instruction.result.0,
                            llvm_type(types, instruction.ty),
                            llvm_operand(value),
                            llvm_type(types, instruction.ty),
                            llvm_operand(value)
                        )
                        .unwrap();
                    }
                }
                SsaOp::Borrow { place, .. } => {
                    let pointer = emit_place_pointer(
                        output,
                        function,
                        place,
                        instruction.result.0,
                        types,
                        structs,
                    );
                    writeln!(
                        output,
                        "  %v{} = getelementptr inbounds i8, ptr {pointer}, i64 0",
                        instruction.result.0
                    )
                    .unwrap();
                }
                SsaOp::Move { source } | SsaOp::View { source, .. } => {
                    let (descriptor, _) = emit_descriptor_value(
                        output,
                        function,
                        source,
                        instruction.result.0,
                        types,
                    );
                    writeln!(
                        output,
                        "  %v{} = select i1 true, {{ ptr, i64 }} {descriptor}, {{ ptr, i64 }} {descriptor}",
                        instruction.result.0
                    )
                    .unwrap();
                }
                SsaOp::Drop { owner } => {
                    let (descriptor, owner_ty) =
                        emit_descriptor_value(output, function, owner, instruction.result.0, types);
                    let element = types
                        .buffer_element(owner_ty)
                        .expect("verified Buffer Drop");
                    let layout = layout_of(
                        types,
                        element,
                        TargetProperties::LINUX_X86_64,
                        structs,
                        enums,
                    )
                    .expect("verified Buffer element layout");
                    writeln!(
                        output,
                        "  %drop_data{} = extractvalue {{ ptr, i64 }} {descriptor}, 0",
                        instruction.result.0
                    )
                    .unwrap();
                    writeln!(
                        output,
                        "  %drop_length{} = extractvalue {{ ptr, i64 }} {descriptor}, 1",
                        instruction.result.0
                    )
                    .unwrap();
                    writeln!(
                        output,
                        "  %drop_size{} = mul i64 %drop_length{}, {}",
                        instruction.result.0, instruction.result.0, layout.size
                    )
                    .unwrap();
                    writeln!(
                        output,
                        "  call void @aether_free(ptr %drop_data{}, i64 %drop_size{}, i64 {})",
                        instruction.result.0, instruction.result.0, layout.align
                    )
                    .unwrap();
                    writeln!(
                        output,
                        "  %v{} = select i1 true, i1 true, i1 true",
                        instruction.result.0
                    )
                    .unwrap();
                }
                SsaOp::BufferAlloc {
                    element_type,
                    length,
                    initial,
                    ..
                } => {
                    writeln!(
                        output,
                        "  %v{} = call {{ ptr, i64 }} @aether_buffer_new_{}(i64 {}, {} {})",
                        instruction.result.0,
                        mangle_type(types, *element_type),
                        llvm_operand(length),
                        llvm_type(types, *element_type),
                        llvm_operand(initial)
                    )
                    .unwrap();
                }
                SsaOp::Aggregate {
                    struct_id: _,
                    fields,
                } => {
                    let aggregate_ty = instruction.ty;
                    if fields.is_empty() {
                        writeln!(
                            output,
                            "  %v{} = select i1 true, {} zeroinitializer, {} zeroinitializer",
                            instruction.result.0,
                            llvm_type(types, aggregate_ty),
                            llvm_type(types, aggregate_ty)
                        )
                        .unwrap();
                    } else {
                        for (position, (field_id, operand)) in fields.iter().enumerate() {
                            let field = field_info(structs, *field_id);
                            let field_ty = operand_type(function, operand);
                            let previous = if position == 0 {
                                "poison".to_string()
                            } else {
                                format!("%agg{}_{}", instruction.result.0, position - 1)
                            };
                            let result_name = if position + 1 == fields.len() {
                                format!("%v{}", instruction.result.0)
                            } else {
                                format!("%agg{}_{}", instruction.result.0, position)
                            };
                            writeln!(
                                output,
                                "  {result_name} = insertvalue {} {previous}, {} {}, {}",
                                llvm_type(types, aggregate_ty),
                                llvm_type(types, field_ty),
                                llvm_operand(operand),
                                field.index
                            )
                            .unwrap();
                        }
                    }
                }
                SsaOp::EnumConstruct {
                    enum_id,
                    variant_id,
                    payloads,
                } => {
                    let info = &enums[enum_id.0 as usize];
                    let variant = &info.variants[variant_id.index as usize];
                    let aggregate_ty = instruction.ty;
                    let tag_result = if payloads.is_empty() {
                        format!("%v{}", instruction.result.0)
                    } else {
                        format!("%enum{}_tag", instruction.result.0)
                    };
                    writeln!(
                        output,
                        "  {tag_result} = insertvalue {} zeroinitializer, i32 {}, 0",
                        llvm_type(types, aggregate_ty),
                        variant.discriminant
                    )
                    .unwrap();
                    for (position, (operand, payload)) in
                        payloads.iter().zip(&variant.payloads).enumerate()
                    {
                        let previous = if position == 0 {
                            tag_result.clone()
                        } else {
                            format!("%enum{}_payload{}", instruction.result.0, position - 1)
                        };
                        let result_name = if position + 1 == payloads.len() {
                            format!("%v{}", instruction.result.0)
                        } else {
                            format!("%enum{}_payload{}", instruction.result.0, position)
                        };
                        writeln!(
                            output,
                            "  {result_name} = insertvalue {} {previous}, {} {}, {}, {}",
                            llvm_type(types, aggregate_ty),
                            llvm_type(types, operand_type(function, operand)),
                            llvm_operand(operand),
                            variant.index + 1,
                            payload.index
                        )
                        .unwrap();
                    }
                }
                SsaOp::EnumDiscriminant { value, enum_id: _ } => {
                    writeln!(
                        output,
                        "  %v{} = extractvalue {} {}, 0",
                        instruction.result.0,
                        llvm_type(types, operand_type(function, value)),
                        llvm_operand(value)
                    )
                    .unwrap();
                }
                SsaOp::EnumPayload {
                    value,
                    enum_id,
                    variant_id,
                    index,
                } => {
                    let info = &enums[enum_id.0 as usize];
                    let variant = &info.variants[variant_id.index as usize];
                    writeln!(
                        output,
                        "  %v{} = extractvalue {} {}, {}, {}",
                        instruction.result.0,
                        llvm_type(types, operand_type(function, value)),
                        llvm_operand(value),
                        variant.index + 1,
                        index
                    )
                    .unwrap();
                }
                SsaOp::ExtractField {
                    aggregate,
                    projections,
                } => {
                    let aggregate_ty = operand_type(function, aggregate);
                    let indices =
                        llvm_projection_indices(types, aggregate_ty, projections, structs);
                    writeln!(
                        output,
                        "  %v{} = extractvalue {} {}, {indices}",
                        instruction.result.0,
                        llvm_type(types, aggregate_ty),
                        llvm_operand(aggregate)
                    )
                    .unwrap();
                }
                SsaOp::InsertField {
                    aggregate,
                    projections,
                    value,
                } => {
                    let aggregate_ty = operand_type(function, aggregate);
                    let value_ty = operand_type(function, value);
                    let indices =
                        llvm_projection_indices(types, aggregate_ty, projections, structs);
                    writeln!(
                        output,
                        "  %v{} = insertvalue {} {}, {} {}, {indices}",
                        instruction.result.0,
                        llvm_type(types, aggregate_ty),
                        llvm_operand(aggregate),
                        llvm_type(types, value_ty),
                        llvm_operand(value)
                    )
                    .unwrap();
                }
                SsaOp::Coerce {
                    kind,
                    operand,
                    from,
                } => {
                    let opcode = match kind {
                        CoercionKind::SignExtend => "sext",
                        CoercionKind::ZeroExtend => "zext",
                        CoercionKind::FloatExtend => "fpext",
                    };
                    writeln!(
                        output,
                        "  %v{} = {opcode} {} {} to {}",
                        instruction.result.0,
                        llvm_type(types, *from),
                        llvm_operand(operand),
                        llvm_type(types, instruction.ty)
                    )
                    .unwrap();
                }
                SsaOp::Cast {
                    kind,
                    operand,
                    from,
                    trap,
                } => {
                    if *trap == Some(TrapKind::ConversionOutOfRange) {
                        conversion_trap = true;
                    }
                    emit_cast(
                        output,
                        types,
                        block.id,
                        instruction.result.0,
                        *kind,
                        operand,
                        *from,
                        instruction.ty,
                        *trap,
                    );
                }
                SsaOp::Unary {
                    op: UnaryOp::NegateIntegerChecked,
                    operand,
                    trap: Some(TrapKind::IntegerOverflow),
                } => {
                    overflow_trap = true;
                    emit_checked(
                        output,
                        block.id,
                        instruction.result.0,
                        &format!(
                            "llvm.ssub.with.overflow.{}",
                            llvm_type(types, instruction.ty)
                        ),
                        &llvm_type(types, instruction.ty),
                        "0",
                        &llvm_operand(operand),
                    );
                }
                SsaOp::Unary {
                    op: UnaryOp::NegateFloat,
                    operand,
                    trap: None,
                } => {
                    writeln!(
                        output,
                        "  %v{} = fneg {} {}",
                        instruction.result.0,
                        llvm_type(types, instruction.ty),
                        llvm_operand(operand)
                    )
                    .unwrap();
                }
                SsaOp::Unary { .. } => unreachable!("verified unary trap contract"),
                SsaOp::Binary {
                    op,
                    left,
                    right,
                    trap,
                    secondary_trap,
                } => match op {
                    BinaryOp::AddIntegerChecked
                    | BinaryOp::SubtractIntegerChecked
                    | BinaryOp::MultiplyIntegerChecked => {
                        overflow_trap = true;
                        let operand_ty = operand_type(function, left);
                        let integer = types.integer_info(operand_ty).expect("verified integer op");
                        let prefix = if integer.is_signed() { 's' } else { 'u' };
                        let opname = match op {
                            BinaryOp::AddIntegerChecked => "add",
                            BinaryOp::SubtractIntegerChecked => "sub",
                            BinaryOp::MultiplyIntegerChecked => "mul",
                            _ => unreachable!(),
                        };
                        let llvm_ty = llvm_type(types, operand_ty);
                        let intrinsic = format!("llvm.{prefix}{opname}.with.overflow.{llvm_ty}");
                        debug_assert_eq!(*trap, Some(TrapKind::IntegerOverflow));
                        emit_checked(
                            output,
                            block.id,
                            instruction.result.0,
                            &intrinsic,
                            &llvm_ty,
                            &llvm_operand(left),
                            &llvm_operand(right),
                        );
                    }
                    BinaryOp::DivideIntegerSignedChecked
                    | BinaryOp::DivideIntegerUnsignedChecked
                    | BinaryOp::RemainderIntegerSignedChecked
                    | BinaryOp::RemainderIntegerUnsignedChecked => {
                        division_trap = true;
                        if matches!(op, BinaryOp::DivideIntegerSignedChecked) {
                            division_overflow_trap = true;
                        }
                        emit_integer_division(
                            output,
                            types,
                            block.id,
                            instruction.result.0,
                            *op,
                            operand_type(function, left),
                            &llvm_operand(left),
                            &llvm_operand(right),
                        );
                        debug_assert_eq!(*trap, Some(TrapKind::DivisionByZero));
                        debug_assert_eq!(
                            *secondary_trap,
                            matches!(op, BinaryOp::DivideIntegerSignedChecked)
                                .then_some(TrapKind::DivisionOverflow)
                        );
                    }
                    BinaryOp::AddFloat
                    | BinaryOp::SubtractFloat
                    | BinaryOp::MultiplyFloat
                    | BinaryOp::DivideFloat => {
                        let opcode = match op {
                            BinaryOp::AddFloat => "fadd",
                            BinaryOp::SubtractFloat => "fsub",
                            BinaryOp::MultiplyFloat => "fmul",
                            BinaryOp::DivideFloat => "fdiv",
                            _ => unreachable!(),
                        };
                        writeln!(
                            output,
                            "  %v{} = {opcode} {} {}, {}",
                            instruction.result.0,
                            llvm_type(types, operand_type(function, left)),
                            llvm_operand(left),
                            llvm_operand(right)
                        )
                        .unwrap();
                    }
                    BinaryOp::Less
                    | BinaryOp::LessEqual
                    | BinaryOp::Greater
                    | BinaryOp::GreaterEqual
                    | BinaryOp::Equal
                    | BinaryOp::NotEqual => {
                        let operand_ty = operand_type(function, left);
                        if types.float_info(operand_ty).is_some() {
                            let predicate = match op {
                                BinaryOp::Less => "olt",
                                BinaryOp::LessEqual => "ole",
                                BinaryOp::Greater => "ogt",
                                BinaryOp::GreaterEqual => "oge",
                                BinaryOp::Equal => "oeq",
                                BinaryOp::NotEqual => "une",
                                _ => unreachable!(),
                            };
                            writeln!(
                                output,
                                "  %v{} = fcmp {predicate} {} {}, {}",
                                instruction.result.0,
                                llvm_type(types, operand_ty),
                                llvm_operand(left),
                                llvm_operand(right)
                            )
                            .unwrap();
                        } else {
                            let signed = types
                                .integer_info(operand_ty)
                                .is_some_and(IntegerType::is_signed);
                            let predicate = match op {
                                BinaryOp::Less => {
                                    if signed {
                                        "slt"
                                    } else {
                                        "ult"
                                    }
                                }
                                BinaryOp::LessEqual => {
                                    if signed {
                                        "sle"
                                    } else {
                                        "ule"
                                    }
                                }
                                BinaryOp::Greater => {
                                    if signed {
                                        "sgt"
                                    } else {
                                        "ugt"
                                    }
                                }
                                BinaryOp::GreaterEqual => {
                                    if signed {
                                        "sge"
                                    } else {
                                        "uge"
                                    }
                                }
                                BinaryOp::Equal => "eq",
                                BinaryOp::NotEqual => "ne",
                                _ => unreachable!(),
                            };
                            writeln!(
                                output,
                                "  %v{} = icmp {predicate} {} {}, {}",
                                instruction.result.0,
                                llvm_type(types, operand_ty),
                                llvm_operand(left),
                                llvm_operand(right)
                            )
                            .unwrap();
                        }
                    }
                },
                SsaOp::Call { callee, args } => {
                    let callee_signature = &signatures[callee.0 as usize];
                    let arguments = args
                        .iter()
                        .zip(&callee_signature.parameters)
                        .map(|(argument, parameter)| {
                            format!(
                                "{} {}",
                                llvm_type(types, parameter.ty),
                                llvm_operand(argument)
                            )
                        })
                        .collect::<Vec<_>>()
                        .join(", ");
                    writeln!(
                        output,
                        "  %v{} = call {} @{}({arguments})",
                        instruction.result.0,
                        llvm_type(types, callee_signature.return_type),
                        bootstrap_symbol(callee_signature, modules, structs, enums, types)
                    )
                    .unwrap();
                }
            }
        }
        match &block.terminator {
            SsaTerminator::Goto(target) => {
                writeln!(output, "  br label %{}", block_label(*target)).unwrap();
            }
            SsaTerminator::Branch {
                condition,
                then_block,
                else_block,
            } => writeln!(
                output,
                "  br i1 {}, label %{}, label %{}",
                llvm_operand(condition),
                block_label(*then_block),
                block_label(*else_block)
            )
            .unwrap(),
            SsaTerminator::Switch {
                discriminant,
                cases,
                otherwise,
                ..
            } => {
                let default = otherwise.map_or_else(
                    || format!("switch_unreachable_bb{}", block.id.0),
                    block_label,
                );
                writeln!(
                    output,
                    "  switch i32 {}, label %{default} [",
                    llvm_operand(discriminant)
                )
                .unwrap();
                for (value, target) in cases {
                    writeln!(output, "    i32 {value}, label %{}", block_label(*target)).unwrap();
                }
                writeln!(output, "  ]").unwrap();
                if otherwise.is_none() {
                    writeln!(output, "{default}:\n  unreachable").unwrap();
                }
            }
            SsaTerminator::Return(value) => writeln!(
                output,
                "  ret {} {}",
                llvm_type(types, signature.return_type),
                llvm_operand(value)
            )
            .unwrap(),
            SsaTerminator::Trap(TrapKind::IntegerOverflow) => {
                overflow_trap = true;
                writeln!(output, "  br label %trap_integer_overflow").unwrap();
            }
            SsaTerminator::Trap(TrapKind::DivisionByZero) => {
                division_trap = true;
                writeln!(output, "  br label %trap_division_by_zero").unwrap();
            }
            SsaTerminator::Trap(TrapKind::ConversionOutOfRange) => {
                conversion_trap = true;
                writeln!(output, "  br label %trap_conversion_out_of_range").unwrap();
            }
            SsaTerminator::Trap(TrapKind::DivisionOverflow) => {
                division_overflow_trap = true;
                writeln!(output, "  br label %trap_division_overflow").unwrap();
            }
            SsaTerminator::Trap(TrapKind::AllocationSizeOverflow) => {
                allocation_size_trap = true;
                writeln!(output, "  br label %trap_allocation_size_overflow").unwrap();
            }
            SsaTerminator::Trap(TrapKind::AllocationFailure) => {
                allocation_failure_trap = true;
                writeln!(output, "  br label %trap_allocation_failure").unwrap();
            }
            SsaTerminator::Trap(TrapKind::IndexOutOfBounds) => {
                bounds_trap = true;
                writeln!(output, "  br label %trap_index_out_of_bounds").unwrap();
            }
        }
    }
    if overflow_trap {
        writeln!(
            output,
            "trap_integer_overflow:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    if division_trap {
        writeln!(
            output,
            "trap_division_by_zero:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    if conversion_trap {
        writeln!(
            output,
            "trap_conversion_out_of_range:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    if division_overflow_trap {
        writeln!(
            output,
            "trap_division_overflow:\n  call void @llvm.trap()\n  unreachable"
        )
        .unwrap();
    }
    if allocation_size_trap {
        writeln!(output, "trap_allocation_size_overflow:\n  ; structured Aether trap: AllocationSizeOverflow\n  call void @llvm.trap()\n  unreachable").unwrap();
    }
    if allocation_failure_trap {
        writeln!(output, "trap_allocation_failure:\n  ; structured Aether trap: AllocationFailure\n  call void @llvm.trap()\n  unreachable").unwrap();
    }
    if bounds_trap {
        writeln!(output, "trap_index_out_of_bounds:\n  ; structured Aether trap: IndexOutOfBounds\n  call void @llvm.trap()\n  unreachable").unwrap();
    }
    writeln!(output, "}}\n").unwrap();
}

fn emit_checked(
    output: &mut String,
    block: BlockId,
    result: u32,
    intrinsic: &str,
    ty: &str,
    left: &str,
    right: &str,
) {
    writeln!(
        output,
        "  %checked{result} = call {{ {ty}, i1 }} @{intrinsic}({ty} {left}, {ty} {right})"
    )
    .unwrap();
    writeln!(
        output,
        "  %v{result} = extractvalue {{ {ty}, i1 }} %checked{result}, 0"
    )
    .unwrap();
    writeln!(
        output,
        "  %overflow{result} = extractvalue {{ {ty}, i1 }} %checked{result}, 1"
    )
    .unwrap();
    writeln!(
        output,
        "  br i1 %overflow{result}, label %trap_integer_overflow, label %{}",
        continuation_label(block, result)
    )
    .unwrap();
    writeln!(output, "{}:", continuation_label(block, result)).unwrap();
}

#[allow(clippy::too_many_arguments)]
fn emit_cast(
    output: &mut String,
    types: &TypeArena,
    block: BlockId,
    result: u32,
    kind: CastKind,
    operand: &SsaOperand,
    from: TypeId,
    to: TypeId,
    trap: Option<TrapKind>,
) {
    let value = llvm_operand(operand);
    match kind {
        CastKind::Identity | CastKind::IntegerReencode => {
            emit_identity(output, types, result, to, &value);
        }
        CastKind::IntegerExtendSigned => {
            writeln!(
                output,
                "  %v{result} = sext {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
        CastKind::IntegerExtendUnsigned => {
            writeln!(
                output,
                "  %v{result} = zext {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
        CastKind::IntegerNarrowChecked | CastKind::IntegerSignednessChecked => {
            if trap == Some(TrapKind::ConversionOutOfRange) {
                emit_integer_cast_check(output, types, block, result, &value, from, to);
            }
            emit_integer_cast_value(output, types, result, &value, from, to);
        }
        CastKind::SignedIntegerToFloat | CastKind::UnsignedIntegerToFloat => {
            let opcode = if kind == CastKind::SignedIntegerToFloat {
                "sitofp"
            } else {
                "uitofp"
            };
            writeln!(
                output,
                "  %v{result} = {opcode} {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
        CastKind::FloatToSignedIntegerChecked | CastKind::FloatToUnsignedIntegerChecked => {
            emit_float_to_integer_check(output, types, block, result, &value, from, to);
            let opcode = if kind == CastKind::FloatToSignedIntegerChecked {
                "fptosi"
            } else {
                "fptoui"
            };
            writeln!(
                output,
                "  %v{result} = {opcode} {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
        CastKind::FloatExtend => {
            writeln!(
                output,
                "  %v{result} = fpext {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
        CastKind::FloatTruncate => {
            writeln!(
                output,
                "  %v{result} = fptrunc {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
    }
}

fn emit_identity(output: &mut String, types: &TypeArena, result: u32, ty: TypeId, value: &str) {
    writeln!(
        output,
        "  %v{result} = select i1 true, {} {value}, {} {value}",
        llvm_type(types, ty),
        llvm_type(types, ty)
    )
    .unwrap();
}

fn emit_integer_cast_check(
    output: &mut String,
    types: &TypeArena,
    block: BlockId,
    result: u32,
    value: &str,
    from: TypeId,
    to: TypeId,
) {
    let source = types
        .integer_info(from)
        .expect("verified integer cast source");
    let target = types
        .integer_info(to)
        .expect("verified integer cast target");
    let properties = TargetProperties::LINUX_X86_64;
    let (source_min, source_max) = source.range(properties);
    let (target_min, target_max) = target.range(properties);
    let predicate_prefix = if source.is_signed() { 's' } else { 'u' };
    let mut conditions = Vec::new();
    if target_min > source_min {
        writeln!(
            output,
            "  %cast_lower{result} = icmp {predicate_prefix}ge {} {value}, {target_min}",
            llvm_type(types, from)
        )
        .unwrap();
        conditions.push(format!("%cast_lower{result}"));
    }
    if target_max < source_max {
        writeln!(
            output,
            "  %cast_upper{result} = icmp {predicate_prefix}le {} {value}, {target_max}",
            llvm_type(types, from)
        )
        .unwrap();
        conditions.push(format!("%cast_upper{result}"));
    }
    let condition = match conditions.as_slice() {
        [condition] => condition.clone(),
        [lower, upper] => {
            writeln!(output, "  %cast_ok{result} = and i1 {lower}, {upper}").unwrap();
            format!("%cast_ok{result}")
        }
        _ => unreachable!("fallible integer cast has at least one range boundary"),
    };
    writeln!(
        output,
        "  br i1 {condition}, label %{}, label %trap_conversion_out_of_range",
        continuation_label(block, result)
    )
    .unwrap();
    writeln!(output, "{}:", continuation_label(block, result)).unwrap();
}

fn emit_integer_cast_value(
    output: &mut String,
    types: &TypeArena,
    result: u32,
    value: &str,
    from: TypeId,
    to: TypeId,
) {
    let properties = TargetProperties::LINUX_X86_64;
    let source = types.integer_info(from).unwrap();
    let target = types.integer_info(to).unwrap();
    match source.bits(properties).cmp(&target.bits(properties)) {
        std::cmp::Ordering::Less => {
            let opcode = if source.is_signed() && target.is_signed() {
                "sext"
            } else {
                "zext"
            };
            writeln!(
                output,
                "  %v{result} = {opcode} {} {value} to {}",
                llvm_type(types, from),
                llvm_type(types, to)
            )
            .unwrap();
        }
        std::cmp::Ordering::Greater => writeln!(
            output,
            "  %v{result} = trunc {} {value} to {}",
            llvm_type(types, from),
            llvm_type(types, to)
        )
        .unwrap(),
        std::cmp::Ordering::Equal => emit_identity(output, types, result, to, value),
    }
}

fn emit_float_to_integer_check(
    output: &mut String,
    types: &TypeArena,
    block: BlockId,
    result: u32,
    value: &str,
    from: TypeId,
    to: TypeId,
) {
    let source = types.float_info(from).unwrap();
    let target = types.integer_info(to).unwrap();
    let (min, max) = target.range(TargetProperties::LINUX_X86_64);
    let (lower_predicate, lower) = if target.is_signed() {
        let minimum = float_boundary(source, min);
        let below = float_boundary(source, min - 1);
        if below == minimum {
            ("oge", minimum)
        } else {
            ("ogt", below)
        }
    } else {
        ("ogt", float_boundary(source, -1))
    };
    let upper = float_boundary(source, max + 1);
    writeln!(
        output,
        "  %cast_lower{result} = fcmp {lower_predicate} {} {value}, {}",
        llvm_type(types, from),
        float_operand(lower)
    )
    .unwrap();
    writeln!(
        output,
        "  %cast_upper{result} = fcmp olt {} {value}, {}",
        llvm_type(types, from),
        float_operand(upper)
    )
    .unwrap();
    writeln!(
        output,
        "  %cast_ok{result} = and i1 %cast_lower{result}, %cast_upper{result}"
    )
    .unwrap();
    writeln!(
        output,
        "  br i1 %cast_ok{result}, label %{}, label %trap_conversion_out_of_range",
        continuation_label(block, result)
    )
    .unwrap();
    writeln!(output, "{}:", continuation_label(block, result)).unwrap();
}

#[allow(clippy::cast_precision_loss)]
fn float_boundary(source: FloatType, value: i128) -> FloatValue {
    match source {
        FloatType::Float32 => FloatValue::Float32((value as f32).to_bits()),
        FloatType::Float64 => FloatValue::Float64((value as f64).to_bits()),
    }
}

#[allow(clippy::too_many_arguments)]
fn emit_integer_division(
    output: &mut String,
    types: &TypeArena,
    block: BlockId,
    result: u32,
    op: BinaryOp,
    ty: TypeId,
    left: &str,
    right: &str,
) {
    let llvm_ty = llvm_type(types, ty);
    writeln!(output, "  %div_zero{result} = icmp eq {llvm_ty} {right}, 0").unwrap();
    let nonzero = if matches!(
        op,
        BinaryOp::DivideIntegerUnsignedChecked | BinaryOp::RemainderIntegerUnsignedChecked
    ) {
        continuation_label(block, result)
    } else {
        format!("bb{}_nonzero_v{result}", block.0)
    };
    writeln!(
        output,
        "  br i1 %div_zero{result}, label %trap_division_by_zero, label %{nonzero}"
    )
    .unwrap();
    writeln!(output, "{nonzero}:").unwrap();
    match op {
        BinaryOp::DivideIntegerUnsignedChecked | BinaryOp::RemainderIntegerUnsignedChecked => {
            let opcode = if matches!(op, BinaryOp::DivideIntegerUnsignedChecked) {
                "udiv"
            } else {
                "urem"
            };
            writeln!(output, "  %v{result} = {opcode} {llvm_ty} {left}, {right}").unwrap();
        }
        BinaryOp::DivideIntegerSignedChecked => {
            let integer = types.integer_info(ty).unwrap();
            let min = integer.range(TargetProperties::LINUX_X86_64).0;
            writeln!(
                output,
                "  %div_min{result} = icmp eq {llvm_ty} {left}, {min}"
            )
            .unwrap();
            writeln!(
                output,
                "  %div_neg_one{result} = icmp eq {llvm_ty} {right}, -1"
            )
            .unwrap();
            writeln!(
                output,
                "  %div_overflow{result} = and i1 %div_min{result}, %div_neg_one{result}"
            )
            .unwrap();
            writeln!(
                output,
                "  br i1 %div_overflow{result}, label %trap_division_overflow, label %{}",
                continuation_label(block, result)
            )
            .unwrap();
            writeln!(output, "{}:", continuation_label(block, result)).unwrap();
            writeln!(output, "  %v{result} = sdiv {llvm_ty} {left}, {right}").unwrap();
        }
        BinaryOp::RemainderIntegerSignedChecked => {
            let integer = types.integer_info(ty).unwrap();
            let min = integer.range(TargetProperties::LINUX_X86_64).0;
            let special = format!("bb{}_remainder_min_v{result}", block.0);
            let normal = format!("bb{}_remainder_normal_v{result}", block.0);
            writeln!(
                output,
                "  %rem_min{result} = icmp eq {llvm_ty} {left}, {min}"
            )
            .unwrap();
            writeln!(
                output,
                "  %rem_neg_one{result} = icmp eq {llvm_ty} {right}, -1"
            )
            .unwrap();
            writeln!(
                output,
                "  %rem_special{result} = and i1 %rem_min{result}, %rem_neg_one{result}"
            )
            .unwrap();
            writeln!(
                output,
                "  br i1 %rem_special{result}, label %{special}, label %{normal}"
            )
            .unwrap();
            writeln!(
                output,
                "{special}:\n  br label %{}",
                continuation_label(block, result)
            )
            .unwrap();
            writeln!(output, "{normal}:").unwrap();
            writeln!(
                output,
                "  %rem_value{result} = srem {llvm_ty} {left}, {right}"
            )
            .unwrap();
            writeln!(output, "  br label %{}", continuation_label(block, result)).unwrap();
            writeln!(output, "{}:", continuation_label(block, result)).unwrap();
            writeln!(
                output,
                "  %v{result} = phi {llvm_ty} [ 0, %{special} ], [ %rem_value{result}, %{normal} ]"
            )
            .unwrap();
        }
        _ => unreachable!("verified integer division opcode"),
    }
}

fn is_checked(op: &SsaOp) -> bool {
    matches!(
        op,
        SsaOp::Unary {
            op: UnaryOp::NegateIntegerChecked,
            ..
        } | SsaOp::Cast {
            trap: Some(TrapKind::ConversionOutOfRange),
            ..
        } | SsaOp::Binary {
            op: BinaryOp::AddIntegerChecked
                | BinaryOp::SubtractIntegerChecked
                | BinaryOp::MultiplyIntegerChecked
                | BinaryOp::DivideIntegerSignedChecked
                | BinaryOp::DivideIntegerUnsignedChecked
                | BinaryOp::RemainderIntegerSignedChecked
                | BinaryOp::RemainderIntegerUnsignedChecked,
            ..
        }
    )
}

fn bootstrap_symbol(
    signature: &FunctionInstanceInfo,
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
    types: &TypeArena,
) -> String {
    let module = &modules[signature.module.0 as usize];
    let base = bootstrap_symbol_for(&module.name, &signature.name);
    if signature.type_arguments.is_empty() {
        base
    } else {
        format!(
            "{base}__g{}",
            signature
                .type_arguments
                .iter()
                .map(|argument| mangle_symbol_type(types, *argument, modules, structs, enums))
                .collect::<Vec<_>>()
                .join("_")
        )
    }
}

fn mangle_symbol_type(
    types: &TypeArena,
    ty: TypeId,
    modules: &[ModuleInfo],
    structs: &[StructInfo],
    enums: &[EnumInfo],
) -> String {
    let nominal = |module: aether_frontend::ModuleId, name: &str, prefix: char| {
        let module = &modules[module.0 as usize].name;
        format!("{prefix}{}_{module}{}_{name}", module.len(), name.len())
    };
    match types.get(ty).expect("verified symbol type") {
        TypeData::Bool => "b".into(),
        TypeData::Integer(integer) => format!("i{integer:?}"),
        TypeData::Float(float) => format!("f{float:?}"),
        TypeData::Struct(id) => {
            let info = &structs[id.0 as usize];
            nominal(info.module, &info.name, 's')
        }
        TypeData::Enum(id) => {
            let info = &enums[id.0 as usize];
            nominal(info.module, &info.name, 'e')
        }
        TypeData::StructInstance(id, args) => {
            let info = &structs[id.0 as usize];
            format!(
                "{}x{}z",
                nominal(info.module, &info.name, 's'),
                types
                    .arguments(*args)
                    .unwrap()
                    .iter()
                    .map(|argument| mangle_symbol_type(types, *argument, modules, structs, enums))
                    .collect::<Vec<_>>()
                    .join("_")
            )
        }
        TypeData::EnumInstance(id, args) => {
            let info = &enums[id.0 as usize];
            format!(
                "{}x{}z",
                nominal(info.module, &info.name, 'e'),
                types
                    .arguments(*args)
                    .unwrap()
                    .iter()
                    .map(|argument| mangle_symbol_type(types, *argument, modules, structs, enums))
                    .collect::<Vec<_>>()
                    .join("_")
            )
        }
        TypeData::Reference { pointee, mutable } => format!(
            "r{}{}",
            if *mutable { "m" } else { "s" },
            mangle_symbol_type(types, *pointee, modules, structs, enums)
        ),
        TypeData::Buffer { element } => format!(
            "B{}",
            mangle_symbol_type(types, *element, modules, structs, enums)
        ),
        TypeData::View { element, mutable } => format!(
            "V{}{}",
            if *mutable { "m" } else { "s" },
            mangle_symbol_type(types, *element, modules, structs, enums)
        ),
        TypeData::GenericParam(_) => panic!("unresolved generic parameter reached symbol mangling"),
    }
}

fn block_label(block: BlockId) -> String {
    format!("bb{}", block.0)
}

fn continuation_label(block: BlockId, result: u32) -> String {
    format!("bb{}_after_v{}", block.0, result)
}

fn llvm_type(types: &TypeArena, ty: TypeId) -> String {
    match types.get(ty).expect("verified backend TypeId") {
        TypeData::Bool => "i1".into(),
        TypeData::Integer(IntegerType::Int8 | IntegerType::Uint8) => "i8".into(),
        TypeData::Integer(IntegerType::Int16 | IntegerType::Uint16) => "i16".into(),
        TypeData::Integer(IntegerType::Int32 | IntegerType::Uint32) => "i32".into(),
        TypeData::Integer(
            IntegerType::Int64 | IntegerType::Uint64 | IntegerType::Isize | IntegerType::Usize,
        ) => "i64".into(),
        TypeData::Float(FloatType::Float32) => "float".into(),
        TypeData::Float(FloatType::Float64) => "double".into(),
        TypeData::Struct(id) => format!("%aether.struct.{}", id.0),
        TypeData::Enum(id) => format!("%aether.enum.{}", id.0),
        TypeData::StructInstance(id, args) => format!(
            "%aether.struct.{}.{}",
            id.0,
            mangle_type_arguments(types, *args)
        ),
        TypeData::EnumInstance(id, args) => format!(
            "%aether.enum.{}.{}",
            id.0,
            mangle_type_arguments(types, *args)
        ),
        TypeData::Reference { .. } => "ptr".into(),
        TypeData::Buffer { .. } | TypeData::View { .. } => "{ ptr, i64 }".into(),
        TypeData::GenericParam(_) => panic!("unresolved generic parameter reached LLVM"),
    }
}

fn mangle_type_arguments(types: &TypeArena, args: aether_frontend::TypeArgsId) -> String {
    types
        .arguments(args)
        .expect("verified type arguments")
        .iter()
        .map(|ty| mangle_type(types, *ty))
        .collect::<Vec<_>>()
        .join("_")
}

fn mangle_type(types: &TypeArena, ty: TypeId) -> String {
    match types.get(ty).expect("verified mangle type") {
        TypeData::Bool => "b".into(),
        TypeData::Integer(integer) => format!("i{integer:?}"),
        TypeData::Float(float) => format!("f{float:?}"),
        TypeData::Struct(id) => format!("s{}", id.0),
        TypeData::Enum(id) => format!("e{}", id.0),
        TypeData::StructInstance(id, args) => {
            format!("s{}x{}z", id.0, mangle_type_arguments(types, *args))
        }
        TypeData::EnumInstance(id, args) => {
            format!("e{}x{}z", id.0, mangle_type_arguments(types, *args))
        }
        TypeData::Reference { pointee, mutable } => format!(
            "r{}{}",
            if *mutable { "m" } else { "s" },
            mangle_type(types, *pointee)
        ),
        TypeData::Buffer { element } => format!("B{}", mangle_type(types, *element)),
        TypeData::View { element, mutable } => format!(
            "V{}{}",
            if *mutable { "m" } else { "s" },
            mangle_type(types, *element)
        ),
        TypeData::GenericParam(_) => panic!("unresolved generic parameter reached mangling"),
    }
}

fn field_info(structs: &[StructInfo], id: FieldId) -> &aether_frontend::FieldInfo {
    structs
        .iter()
        .find_map(|info| info.fields.iter().find(|field| field.id == id))
        .expect("verified field identity")
}

fn llvm_projection_indices(
    types: &TypeArena,
    mut ty: TypeId,
    projections: &[FieldId],
    structs: &[StructInfo],
) -> String {
    projections
        .iter()
        .map(|field_id| {
            let owner = types.struct_id(ty).expect("verified projection owner");
            let field = structs[owner.0 as usize]
                .fields
                .iter()
                .find(|field| field.id == *field_id)
                .expect("verified projection field");
            ty = concrete_struct_member(types, structs, ty, field.ty);
            field.index.to_string()
        })
        .collect::<Vec<_>>()
        .join(", ")
}

fn emit_place_pointer(
    output: &mut String,
    function: &SsaFunction,
    place: &SsaPlace,
    result: u32,
    types: &TypeArena,
    structs: &[StructInfo],
) -> String {
    if let Some((
        position,
        SsaPlaceProjection::Index {
            index,
            element_type,
            ..
        },
    )) = place
        .projections
        .iter()
        .enumerate()
        .find(|(_, projection)| matches!(projection, SsaPlaceProjection::Index { .. }))
    {
        debug_assert_eq!(
            position, 0,
            "V10 owning aggregates cannot contain Buffer fields"
        );
        let descriptor_place = SsaPlace {
            base: place.base.clone(),
            projections: Vec::new(),
        };
        let (descriptor, _) =
            emit_descriptor_value(output, function, &descriptor_place, result, types);
        let mut pointer = format!("%place{result}_index");
        writeln!(
            output,
            "  {pointer} = call ptr @aether_index_{}({{ ptr, i64 }} {descriptor}, i64 {})",
            mangle_type(types, *element_type),
            llvm_operand(index)
        )
        .unwrap();
        let mut ty = *element_type;
        for (field_position, projection) in place.projections[position + 1..].iter().enumerate() {
            let SsaPlaceProjection::Field(field_id) = projection else {
                unreachable!("Vertical-10 does not admit multidimensional indexing")
            };
            let owner = types
                .struct_id(ty)
                .expect("verified indexed field projection");
            let field = structs[owner.0 as usize]
                .fields
                .iter()
                .find(|field| field.id == *field_id)
                .expect("verified indexed field identity");
            let next = format!("%place{result}_field{field_position}");
            writeln!(
                output,
                "  {next} = getelementptr inbounds {}, ptr {pointer}, i32 0, i32 {}",
                llvm_type(types, ty),
                field.index
            )
            .unwrap();
            pointer = next;
            ty = concrete_struct_member(types, structs, ty, field.ty);
        }
        return pointer;
    }
    let (base, root_ty) = match &place.base {
        SsaPlaceBase::MemoryLocal(local) => {
            let memory = function
                .memory_locals
                .iter()
                .find(|memory| memory.local == *local)
                .expect("verified memory local");
            (format!("%m{}", local.0), memory.ty)
        }
        SsaPlaceBase::Dereference { reference, .. } => {
            let reference_ty = operand_type(function, reference);
            let (pointee, _) = types
                .reference_info(reference_ty)
                .expect("verified reference place");
            (llvm_operand(reference), pointee)
        }
        SsaPlaceBase::Value(_) => unreachable!("descriptor value place requires index projection"),
    };
    if place.projections.is_empty() {
        return base;
    }
    let fields = place
        .projections
        .iter()
        .map(|projection| match projection {
            SsaPlaceProjection::Field(field) => *field,
            SsaPlaceProjection::Index { .. } => unreachable!(),
        })
        .collect::<Vec<_>>();
    let indices = llvm_projection_indices(types, root_ty, &fields, structs)
        .split(", ")
        .map(|index| format!("i32 {index}"))
        .collect::<Vec<_>>()
        .join(", ");
    let pointer = format!("%place{result}");
    writeln!(
        output,
        "  {pointer} = getelementptr inbounds {}, ptr {base}, i32 0, {indices}",
        llvm_type(types, root_ty)
    )
    .unwrap();
    pointer
}

fn emit_descriptor_value(
    output: &mut String,
    function: &SsaFunction,
    place: &SsaPlace,
    result: u32,
    types: &TypeArena,
) -> (String, TypeId) {
    assert!(
        place.projections.is_empty(),
        "descriptor place must be whole"
    );
    match &place.base {
        SsaPlaceBase::Value(value) => (llvm_operand(value), operand_type(function, value)),
        SsaPlaceBase::MemoryLocal(local) => {
            let memory = function
                .memory_locals
                .iter()
                .find(|memory| memory.local == *local)
                .expect("verified descriptor memory local");
            let value = format!("%descriptor{result}");
            writeln!(output, "  {value} = load {{ ptr, i64 }}, ptr %m{}", local.0).unwrap();
            (value, memory.ty)
        }
        SsaPlaceBase::Dereference { reference, .. } => {
            let reference_ty = operand_type(function, reference);
            let (pointee, _) = types
                .reference_info(reference_ty)
                .expect("verified descriptor reference");
            let value = format!("%descriptor{result}");
            writeln!(
                output,
                "  {value} = load {{ ptr, i64 }}, ptr {}",
                llvm_operand(reference)
            )
            .unwrap();
            (value, pointee)
        }
    }
}

fn concrete_struct_member(
    types: &TypeArena,
    structs: &[StructInfo],
    aggregate: TypeId,
    member: TypeId,
) -> TypeId {
    let Some(TypeData::StructInstance(id, args)) = types.get(aggregate) else {
        return member;
    };
    let parameters = &structs[id.0 as usize].generic_parameters;
    let substitution = Substitution::new(
        parameters.iter().map(|parameter| parameter.id),
        types
            .arguments(*args)
            .expect("verified struct arguments")
            .iter()
            .copied(),
    );
    types
        .substituted_existing(member, &substitution)
        .expect("verified concrete struct member")
}

fn concrete_enum_member(
    types: &TypeArena,
    enums: &[EnumInfo],
    aggregate: TypeId,
    member: TypeId,
) -> TypeId {
    let Some(TypeData::EnumInstance(id, args)) = types.get(aggregate) else {
        return member;
    };
    let parameters = &enums[id.0 as usize].generic_parameters;
    let substitution = Substitution::new(
        parameters.iter().map(|parameter| parameter.id),
        types
            .arguments(*args)
            .expect("verified enum arguments")
            .iter()
            .copied(),
    );
    types
        .substituted_existing(member, &substitution)
        .expect("verified concrete enum member")
}

fn llvm_operand(operand: &SsaOperand) -> String {
    match operand {
        SsaOperand::Value(value) => format!("%v{}", value.0),
        SsaOperand::Int { value, .. } => value.to_string(),
        SsaOperand::Float { value, .. } => float_operand(*value),
        SsaOperand::Bool(value) => value.to_string(),
    }
}

fn operand_type(function: &SsaFunction, operand: &SsaOperand) -> TypeId {
    match operand {
        SsaOperand::Int { ty, .. } | SsaOperand::Float { ty, .. } => *ty,
        SsaOperand::Bool(_) => TypeId::BOOL,
        SsaOperand::Value(value) => function
            .parameters
            .iter()
            .find(|parameter| parameter.value == *value)
            .map(|parameter| parameter.ty)
            .or_else(|| {
                function.blocks.iter().find_map(|block| {
                    block
                        .phis
                        .iter()
                        .find(|phi| phi.result == *value)
                        .map(|phi| phi.ty)
                        .or_else(|| {
                            block
                                .instructions
                                .iter()
                                .find(|instruction| instruction.result == *value)
                                .map(|instruction| instruction.ty)
                        })
                })
            })
            .expect("verified SSA value has definition"),
    }
}

fn float_operand(value: FloatValue) -> String {
    let bits = match value {
        // LLVM spells non-double hexadecimal constants with the exact double
        // encoding of the represented value.
        FloatValue::Float32(bits) => f64::from(f32::from_bits(bits)).to_bits(),
        FloatValue::Float64(bits) => bits,
    };
    format!("0x{bits:016X}")
}

/// Exposes deterministic bootstrap mangling for qualification without making it public ABI.
#[must_use]
pub fn bootstrap_symbol_for(module: &str, function: &str) -> String {
    format!(
        "__aether_v2_m{}_{}_f{}_{}",
        module.len(),
        escape_symbol_part(module),
        function.len(),
        escape_symbol_part(function)
    )
}

fn escape_symbol_part(name: &str) -> String {
    let mut escaped = String::new();
    for byte in name.bytes() {
        if byte.is_ascii_alphanumeric() {
            escaped.push(char::from(byte));
        } else {
            write!(escaped, "_{byte:02x}").unwrap();
        }
    }
    escaped
}

#[cfg(test)]
mod tests {
    use super::*;
    use aether_frontend::{SourceFile, analyze, parse_source};
    use aether_middle::{build_ssa, lower_hir, verify_mir, verify_ssa};

    fn llvm(text: &str) -> String {
        let hir = analyze(parse_source(&SourceFile::new("test.ae", text)).unwrap()).unwrap();
        let mir = verify_mir(lower_hir(hir)).unwrap();
        let ssa = verify_ssa(build_ssa(&mir)).unwrap();
        emit_llvm(&ssa, &TargetDescriptor::linux_x86_64())
    }

    #[test]
    fn emits_checked_arithmetic_and_phi() {
        let output = llvm("int main(){int i=0;while(i<3){i=i+1;}return i;}");
        assert!(output.contains("llvm.sadd.with.overflow.i64"));
        assert!(output.contains(" = phi i64 "));
        assert!(output.contains("trap_integer_overflow"));
        assert!(!output.contains(" add nsw "));
    }

    #[test]
    fn emits_functions_bool_signatures_calls_and_wrapper() {
        let output = llvm(
            "bool positive(int x){return x>0;}int main(){if(positive(5)){return 1;}return 0;}",
        );
        assert!(output.contains("define i1 @__aether_v2_m4_main_f8_positive(i64 %v0)"));
        assert!(output.contains("call i1 @__aether_v2_m4_main_f8_positive(i64 5)"));
        assert!(output.contains("define i32 @main()"));
    }

    #[test]
    fn emits_index_support_for_view_only_signatures_without_owner_runtime() {
        let output = llvm("int read(View<int> values){return values[0];}int main(){return 0;}");
        assert!(output.contains("define internal ptr @aether_index_iInt64"));
        assert!(!output.contains("@aether_buffer_new_iInt64"));
        assert!(!output.contains("@malloc"));
        assert!(!output.contains("@aether_allocation_balance"));
    }

    #[test]
    fn bootstrap_symbols_are_identity_based_and_deterministic() {
        assert_eq!(
            bootstrap_symbol_for("math", "add"),
            "__aether_v2_m4_math_f3_add"
        );
        assert_ne!(
            bootstrap_symbol_for("a_b", "c"),
            bootstrap_symbol_for("a", "b_c")
        );
    }

    #[test]
    fn emits_explicit_scalar_conversion_instructions_and_checks() {
        let output = llvm(
            "int main(){int64 x=127;int8 y=int8(x);uint16 u=uint16(y);float64 f=double(u);float32 g=float32(f);return int32(g);}",
        );
        assert!(output.contains("trunc i64"));
        assert!(output.contains("zext i8"));
        assert!(output.contains("uitofp i16"));
        assert!(output.contains("fptrunc double"));
        assert!(output.contains("fptosi float"));
        assert!(output.contains("trap_conversion_out_of_range"));
    }

    #[test]
    fn emits_checked_integer_and_ieee_float_division() {
        let output = llvm(
            "int64 q(int64 a,int64 b){return a/b;}int64 r(int64 a,int64 b){return a%b;}float64 f(float64 a,float64 b){return a/b;}int main(){return q(5,2)+r(5,2)+int(f(4.0,2.0));}",
        );
        assert!(output.contains("icmp eq i64"));
        assert!(output.contains("trap_division_by_zero"));
        assert!(output.contains("trap_division_overflow"));
        assert!(output.contains(" = sdiv i64 "));
        assert!(output.contains(" = srem i64 "));
        assert!(output.contains(" = fdiv double "));
    }

    #[test]
    fn emits_typed_enum_envelope_payload_ops_and_switch() {
        let output = llvm(
            "enum E{A,B(int,bool),}int main(){E e=E.B(42,true);match(e){E.A=>{return 0;}E.B(x,yes)=>{if(yes){return x;}return 0;}}}",
        );
        assert!(output.contains("%aether.enum.0 = type { i32, {  }, { i64, i1 } }"));
        assert!(output.contains("insertvalue %aether.enum.0"));
        assert!(output.contains("extractvalue %aether.enum.0"));
        assert!(output.contains("switch i32"));
    }
}
