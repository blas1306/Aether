//! Qualification for source-built environment tool artifacts.

use std::fs;
use std::path::PathBuf;
use std::process::Command;

use aether_driver::{
    CompilationOptions, DriverRequest, DriverResponse, ManagedToolBuildRequest, OptimizationLevel,
    PackageMetadata, PackageName, PackageVersion, ProjectKind, ProjectPlan, execute,
};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-managed-tool-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir_all(path.join("source/src")).unwrap();
        fs::create_dir(path.join("environment state")).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn managed_tool_builds_outside_source_and_runs_at_o0_and_o2() {
    let directory = Directory::new();
    let source = directory.0.join("source");
    fs::write(
        source.join("aether.toml"),
        "[package]\nname='managedTool'\nversion='1.0.0'\n[application]\n",
    )
    .unwrap();
    fs::write(source.join("src/main.ae"), "int main(){return 0;}\n").unwrap();
    let metadata = PackageMetadata {
        name: PackageName::new("managedTool").unwrap(),
        version: PackageVersion::new("1.0.0").unwrap(),
        aether: None,
    };
    let plan = ProjectPlan::new(
        &source,
        source.join("aether.toml"),
        metadata,
        source.join("src/main.ae"),
        ProjectKind::Application,
    )
    .unwrap();
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let output = directory
            .0
            .join("environment state")
            .join(format!("tool-{optimization:?}"));
        let result = execute(DriverRequest::BuildManagedTool(ManagedToolBuildRequest {
            input: plan.clone(),
            compilation: CompilationOptions {
                optimization,
                emits: Vec::new(),
            },
            output: output.clone(),
        }))
        .unwrap();
        assert!(matches!(result, DriverResponse::Built { .. }));
        assert!(Command::new(output).status().unwrap().success());
    }
    assert!(!source.join(".aether").exists());
}
