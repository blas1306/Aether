//! EXPENSE-TRACKER-ALPT1-CODEC-V1 qualification.

use std::{fs, path::PathBuf, process::Command};

use aether_driver::{
    ClangToolchain, CompilationSession, Emit, OptimizationLevel, compile_session_with_optimization,
};

struct Artifact(PathBuf);

impl Artifact {
    fn new(optimization: OptimizationLevel) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        Self(std::env::temp_dir().join(format!(
            "aether-expense-alpt1-{optimization:?}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        )))
    }
}

impl Drop for Artifact {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.0);
    }
}

fn fixture(relative: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../tests/modules/expense_tracker_alpt1_codec_v1")
        .join(relative)
}

#[test]
fn codec_and_malformed_corpus_run_at_o0_o2() {
    let entry = fixture("main.ae");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let compilation = compile_session_with_optimization(
            CompilationSession::discover(&entry).unwrap(),
            &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
            optimization,
        )
        .unwrap_or_else(|errors| panic!("{optimization:?}: {errors:#?}"));
        for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
            let dump = &compilation.dumps[&phase];
            for operation in ["ByteAt", "ByteSlice", "ParseInt", "ParseDouble"] {
                assert!(dump.contains(operation), "{phase:?} lacks {operation}");
            }
        }
        let artifact = Artifact::new(optimization);
        ClangToolchain::default()
            .with_optimization(optimization)
            .link_executable(&compilation.llvm, &artifact.0)
            .unwrap();
        assert_eq!(
            Command::new(&artifact.0).status().unwrap().code(),
            Some(0),
            "{optimization:?}"
        );
    }
}

#[test]
fn decoder_uses_only_the_public_byte_and_numeric_surface() {
    let source = fs::read_to_string(fixture("codec.ae")).unwrap();
    for required in [
        "std.Text.byteAt",
        "std.Text.byteSlice",
        "std.Text.parseInt",
        "std.Text.parseDouble",
        "byteLength",
        "str(",
    ] {
        assert!(source.contains(required), "missing {required}");
    }
    for forbidden in [
        "std.Text.substring",
        "std.Text.split",
        "std.Text.lines",
        "std.Process",
        "writeTextAtomic",
        "appendText",
    ] {
        assert!(!source.contains(forbidden), "unexpected {forbidden}");
    }
}
