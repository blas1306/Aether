//! Direct typed-driver qualification for CLI-V1-BOOTSTRAP.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use aether_driver::{
    BuildRequest, CheckRequest, ClangToolchain, CompilationOptions, DriverRequest, DriverResponse,
    OptimizationLevel, RunRequest, StandaloneFile, execute_with_toolchain,
};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-cli-v1-driver-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn source(&self, text: &str) -> StandaloneFile {
        let path = self.0.join("main.ae");
        fs::write(&path, text).unwrap();
        StandaloneFile::new(path).unwrap()
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn options(optimization: OptimizationLevel) -> CompilationOptions {
    CompilationOptions {
        optimization,
        emits: Vec::new(),
    }
}

fn driver_temporaries() -> BTreeSet<PathBuf> {
    let prefix = format!("aether-next-{}-", std::process::id());
    fs::read_dir(std::env::temp_dir())
        .unwrap()
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .filter(|path| {
            path.file_name()
                .and_then(|name| name.to_str())
                .is_some_and(|name| name.starts_with(&prefix))
        })
        .collect()
}

#[test]
fn check_is_real_semantic_analysis_without_backend_or_clang() {
    let directory = Directory::new("check");
    let input = directory.source("int main(){return 0;}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let response = execute_with_toolchain(
            DriverRequest::Check(CheckRequest {
                input: input.clone(),
                compilation: options(optimization),
            }),
            ClangToolchain::new("definitely-not-a-real-clang"),
        )
        .unwrap();
        let DriverResponse::Checked(checked) = response else {
            panic!("check returned the wrong response variant");
        };
        assert!(checked.timings_ns.contains_key("middle.ssa_verify"));
        assert!(!checked.timings_ns.contains_key("backend.llvm"));
        assert!(!directory.0.join("main").exists());
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn typed_build_retains_and_typed_run_cleans_at_o0_and_o2() {
    let directory = Directory::new("native");
    let input = directory.source("int main(){return 23;}");
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let artifact = directory.0.join(format!("program-{optimization:?}"));
        let built = execute_with_toolchain(
            DriverRequest::Build(BuildRequest {
                input: input.clone(),
                compilation: options(optimization),
                output: artifact.clone(),
            }),
            ClangToolchain::default(),
        )
        .unwrap();
        assert!(matches!(built, DriverResponse::Built { .. }));
        assert!(artifact.is_file());

        let before = driver_temporaries();
        let ran = execute_with_toolchain(
            DriverRequest::Run(RunRequest {
                input: input.clone(),
                compilation: options(optimization),
                program_args: Vec::new(),
            }),
            ClangToolchain::default(),
        )
        .unwrap();
        let DriverResponse::Ran { status, .. } = ran else {
            panic!("run returned the wrong response variant");
        };
        assert_eq!(status.code(), Some(23));
        assert_eq!(driver_temporaries(), before);
    }
}

#[test]
fn standalone_type_rejects_non_files_and_non_ae_paths() {
    let directory = Directory::new("target");
    assert!(StandaloneFile::new(&directory.0).is_err());
    let text = directory.0.join("main.txt");
    fs::write(&text, "int main(){return 0;}").unwrap();
    assert!(StandaloneFile::new(text).is_err());
    assert!(StandaloneFile::new(Path::new("missing.ae")).is_err());
}
