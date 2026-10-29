//! SSA-STORE-PROVENANCE-V1 independent verifier qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{ClangToolchain, Emit, OptimizationLevel, compile_source_with_optimization};
use aether_frontend::{SourceFile, analyze, parse_source};
use aether_middle::{
    DescriptorCommitKind, SsaIr, SsaOp, SsaOperand, StoreProvenance, ValueId, build_ssa, lower_hir,
    verify_mir, verify_ssa,
};

fn raw(source: &str) -> SsaIr {
    let source = SourceFile::new("ssa_store_provenance_v1.ae", source);
    let hir = analyze(parse_source(&source).unwrap()).unwrap();
    build_ssa(&verify_mir(lower_hir(hir)).unwrap())
}

fn stores(ssa: &SsaIr) -> Vec<StoreProvenance> {
    ssa.functions
        .iter()
        .flat_map(|function| &function.blocks)
        .flat_map(|block| &block.instructions)
        .filter_map(|instruction| match instruction.op {
            SsaOp::Store { provenance, .. } => Some(provenance),
            _ => None,
        })
        .collect()
}

struct Output(PathBuf);

impl Drop for Output {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

const ALL_FORMS: &str = r"
void copyThrough(ref mut int value){*value=7;return;}
void pushThrough(ref mut List<int> values){push(*values,3);return;}
void reserveThrough(ref mut List<int> values){reserve(*values,8);return;}
void addThrough(ref mut Matrix<int> value){Vector<int,Row> row=[2];(*value).add(row);return;}
void observe(ref Buffer<int> value){return;}
int main(){
  int scalar=1;copyThrough(&mut scalar);
  Buffer<int> owner=Buffer<int>(1,1);observe(&owner);owner=Buffer<int>(1,2);
  List<int> values={1};pushThrough(&mut values);reserveThrough(&mut values);
  Matrix<int> matrix=[];addThrough(&mut matrix);
  return scalar+owner[0]+values[1]+matrix[1,1]-14;
}";

#[test]
fn all_closed_store_provenance_forms_are_emitted_and_verified() {
    let ssa = raw(ALL_FORMS);
    verify_ssa(ssa.clone()).unwrap();
    let provenance = stores(&ssa);
    for required in [
        StoreProvenance::Copy,
        StoreProvenance::Initialize,
        StoreProvenance::RootTransfer,
        StoreProvenance::DescriptorCommit(DescriptorCommitKind::ListPush),
        StoreProvenance::DescriptorCommit(DescriptorCommitKind::ListReserve),
        StoreProvenance::DescriptorCommit(DescriptorCommitKind::MatrixAdd),
    ] {
        assert!(
            provenance.contains(&required),
            "missing {required:?}: {provenance:?}"
        );
    }
}

#[test]
fn valid_programs_reverify_at_o0_and_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_source_with_optimization(
            &SourceFile::new("ssa_store_provenance_v1.ae", ALL_FORMS),
            &[Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap();
        assert!(compilation.dumps[&Emit::Ssa].contains("RootTransfer"));
        assert!(compilation.dumps[&Emit::Ssa].contains("DescriptorCommit"));
        let output = Output(std::env::temp_dir().join(format!(
            "aether-ssa-store-provenance-{:?}-{}",
            optimization,
            std::process::id()
        )));
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &output.0)
            .unwrap();
        assert_eq!(Command::new(&output.0).status().unwrap().code(), Some(0));
    }
}

#[test]
fn labels_cannot_authorize_owning_stores_or_wrong_typed_producers() {
    let mut external = raw(
        "void replace(ref mut Buffer<int>x){Buffer<int>n=Buffer<int>(1,2);*x=n;}int main(){Buffer<int>x=Buffer<int>(1,1);replace(&mut x);return 0;}",
    );
    let replacement = external
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| matches!(instruction.op, SsaOp::ReplaceOwned { .. }))
        .unwrap();
    let SsaOp::ReplaceOwned {
        destination, value, ..
    } = replacement.op.clone()
    else {
        unreachable!()
    };
    replacement.op = SsaOp::Store {
        place: destination,
        value,
        provenance: StoreProvenance::DescriptorCommit(DescriptorCommitKind::ListPush),
    };
    assert!(verify_ssa(external).is_err());

    let mut wrong_kind = raw(
        "void f(ref mut List<int>x){push(*x,2);return;}int main(){List<int>x={1};f(&mut x);return 0;}",
    );
    let store = wrong_kind
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::DescriptorCommit(_),
                    ..
                }
            )
        })
        .unwrap();
    let SsaOp::Store { provenance, .. } = &mut store.op else {
        unreachable!()
    };
    *provenance = StoreProvenance::DescriptorCommit(DescriptorCommitKind::ListReserve);
    assert!(verify_ssa(wrong_kind).is_err());
}

#[test]
fn descriptor_commit_requires_exact_source_destination_single_use_and_region() {
    let source = "void f(ref mut List<int>x){push(*x,2);return;}int main(){List<int>x={1};f(&mut x);return 0;}";

    let mut wrong_value = raw(source);
    let parameter = wrong_value.functions[0].parameters[0].value;
    let store = wrong_value.functions[0].blocks[0]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.op, SsaOp::Store { .. }))
        .unwrap();
    let SsaOp::Store { value, .. } = &mut store.op else {
        unreachable!()
    };
    *value = SsaOperand::Value(parameter);
    assert!(verify_ssa(wrong_value).is_err());

    let mut wrong_source = raw(source);
    let operation = wrong_source.functions[0].blocks[0]
        .instructions
        .iter_mut()
        .find(|instruction| matches!(instruction.op, SsaOp::ListPush { .. }))
        .unwrap();
    let SsaOp::ListPush { source: place, .. } = &mut operation.op else {
        unreachable!()
    };
    place
        .projections
        .push(aether_middle::SsaPlaceProjection::Field(
            aether_frontend::FieldId(u32::MAX),
        ));
    assert!(verify_ssa(wrong_source).is_err());

    let mut split = raw(source);
    let function = &mut split.functions[0];
    let next = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .map(|instruction| instruction.result.0)
        .max()
        .unwrap()
        + 1;
    let block = &mut function.blocks[0];
    let store_index = block
        .instructions
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::Store { .. }))
        .unwrap();
    let span = block.instructions[store_index].span;
    block.instructions.insert(
        store_index,
        aether_middle::SsaInstruction {
            result: ValueId(next),
            ty: aether_frontend::TypeId::BOOL,
            op: SsaOp::Use(SsaOperand::Bool(true)),
            span,
            unwind: None,
            binding: None,
        },
    );
    assert!(verify_ssa(split).is_err());

    let mut duplicate = raw(source);
    let function = &mut duplicate.functions[0];
    let next = function
        .blocks
        .iter()
        .flat_map(|block| &block.instructions)
        .map(|instruction| instruction.result.0)
        .max()
        .unwrap()
        + 1;
    let block = &mut function.blocks[0];
    let original = block
        .instructions
        .iter()
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::DescriptorCommit(_),
                    ..
                }
            )
        })
        .unwrap()
        .clone();
    block.instructions.push(aether_middle::SsaInstruction {
        result: ValueId(next),
        ..original
    });
    assert!(verify_ssa(duplicate).is_err());
}

#[test]
fn root_transfer_requires_capture_publish_drop_order_and_unique_drop() {
    let source = "void see(ref Buffer<int>x){return;}int main(){Buffer<int>x=Buffer<int>(1,1);see(&x);x=Buffer<int>(1,2);return x[0]-2;}";
    let mut reordered = raw(source);
    let block = reordered.functions[1]
        .blocks
        .iter_mut()
        .find(|block| {
            block.instructions.iter().any(|instruction| {
                matches!(
                    instruction.op,
                    SsaOp::Store {
                        provenance: StoreProvenance::RootTransfer,
                        ..
                    }
                )
            })
        })
        .unwrap();
    let store = block
        .instructions
        .iter()
        .position(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::RootTransfer,
                    ..
                }
            )
        })
        .unwrap();
    let drop = block.instructions[store + 1..]
        .iter()
        .position(|instruction| matches!(instruction.op, SsaOp::Drop { .. }))
        .unwrap()
        + store
        + 1;
    block.instructions.swap(store, drop);
    assert!(verify_ssa(reordered).is_err());

    let mut wrong_label = raw(source);
    let store = wrong_label.functions[1]
        .blocks
        .iter_mut()
        .flat_map(|block| &mut block.instructions)
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::RootTransfer,
                    ..
                }
            )
        })
        .unwrap();
    let SsaOp::Store { provenance, .. } = &mut store.op else {
        unreachable!()
    };
    *provenance = StoreProvenance::Initialize;
    assert!(verify_ssa(wrong_label).is_err());

    let mut omitted = raw(source);
    let block = omitted.functions[1]
        .blocks
        .iter_mut()
        .find(|block| {
            block.instructions.iter().any(|instruction| {
                matches!(
                    instruction.op,
                    SsaOp::Store {
                        provenance: StoreProvenance::RootTransfer,
                        ..
                    }
                )
            })
        })
        .unwrap();
    let store = block
        .instructions
        .iter()
        .position(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Store {
                    provenance: StoreProvenance::RootTransfer,
                    ..
                }
            )
        })
        .unwrap();
    let old_drop = block.instructions[store + 1..]
        .iter_mut()
        .find(|instruction| {
            matches!(
                instruction.op,
                SsaOp::Drop {
                    owner: aether_middle::SsaPlace {
                        base: aether_middle::SsaPlaceBase::Value(_),
                        ..
                    }
                }
            )
        })
        .unwrap();
    old_drop.op = SsaOp::Use(SsaOperand::Bool(true));
    assert!(verify_ssa(omitted).is_err());
}
