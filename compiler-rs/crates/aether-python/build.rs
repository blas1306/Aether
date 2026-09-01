//! Build and stage the native executables beside the productive `PyO3` wheel.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const DISTRIBUTION: &str = "aether-compiler-core";
const PACKAGE_VERSION: &str = "1.0.0rc4";
const NATIVE_PRODUCT_VERSION: &str = "0.1.0";

struct NativeBinary<'a> {
    package: &'a str,
    binary: &'a str,
    file_name: &'a str,
}

#[allow(clippy::too_many_lines)]
fn main() {
    println!("cargo:rerun-if-env-changed=AETHER_COMPILER_CORE_BUILD_IDENTITY");
    println!("cargo:rerun-if-env-changed=AETHER_COMPILER_CORE_COMPANION");
    println!("cargo:rerun-if-env-changed=AETHER_COMPILER_CORE_INITIAL_IR_VERIFIER");
    if env::var_os("CARGO_FEATURE_PRODUCTIVE_DISTRIBUTION").is_none() {
        return;
    }

    let manifest_dir = PathBuf::from(required_env("CARGO_MANIFEST_DIR"));
    let workspace = manifest_dir
        .parent()
        .and_then(Path::parent)
        .expect("aether-python must remain inside compiler-rs/crates");
    let repository = workspace
        .parent()
        .expect("compiler-rs must remain inside the Aether repository");
    let out_dir = PathBuf::from(required_env("OUT_DIR"));
    let target = required_env("TARGET");
    let target_os = required_env("CARGO_CFG_TARGET_OS");
    let profile = required_env("PROFILE");
    let build_identity = env::var("AETHER_COMPILER_CORE_BUILD_IDENTITY")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .unwrap_or_else(|| repository_identity(repository));

    println!("cargo:rustc-env=AETHER_COMPILER_CORE_PACKAGE_VERSION={PACKAGE_VERSION}");
    println!("cargo:rustc-env=AETHER_COMPILER_CORE_BUILD_IDENTITY={build_identity}");
    println!("cargo:rerun-if-changed=../aether-verifier/src");
    println!("cargo:rerun-if-changed=../aether-ir/src");

    let companion_binary_name = if target_os == "windows" {
        "aether-ssa-shadow.exe"
    } else {
        "aether-ssa-shadow"
    };
    let companion_source = match env::var_os("AETHER_COMPILER_CORE_COMPANION") {
        Some(path) => PathBuf::from(path),
        None => build_native_binary(
            workspace,
            &out_dir,
            &target,
            &profile,
            &build_identity,
            &NativeBinary {
                package: "aether-verifier",
                binary: "aether-ssa-shadow",
                file_name: companion_binary_name,
            },
        ),
    };
    stage_executable(
        &companion_source,
        &out_dir.join(companion_binary_name),
        "native compiler-core companion",
    );

    let verifier_binary_name = if target_os == "windows" {
        "aether-ir-verifier.exe"
    } else {
        "aether-ir-verifier"
    };
    let verifier_source = match env::var_os("AETHER_COMPILER_CORE_INITIAL_IR_VERIFIER") {
        Some(path) => PathBuf::from(path),
        None => build_native_binary(
            workspace,
            &out_dir,
            &target,
            &profile,
            &build_identity,
            &NativeBinary {
                package: "aether-ir-verifier",
                binary: "aether-ir-verifier",
                file_name: verifier_binary_name,
            },
        ),
    };
    stage_executable(
        &verifier_source,
        &out_dir.join(verifier_binary_name),
        "native Initial IR verifier",
    );

    let manifest = format!(
        concat!(
            "{{\n",
            "  \"binary\": \"{companion_binary_name}\",\n",
            "  \"build_identity\": \"{build_identity}\",\n",
            "  \"compiler_core_api_version\": 1,\n",
            "  \"distribution\": \"{distribution}\",\n",
            "  \"initial_ir_verifier_binary\": \"{verifier_binary_name}\",\n",
            "  \"input_schema_versions\": [1],\n",
            "  \"language_package_version\": \"{package_version}\",\n",
            "  \"manifest_schema_version\": 1,\n",
            "  \"native_product_version\": \"{native_product_version}\",\n",
            "  \"output_schema_versions\": [2],\n",
            "  \"package_version\": \"{package_version}\",\n",
            "  \"product\": \"aether-ssa-shadow\",\n",
            "  \"protocol_version\": 1,\n",
            "  \"target\": \"{target}\",\n",
            "  \"wheel_record_integrity_required\": true\n",
            "}}\n"
        ),
        companion_binary_name = json_escape(companion_binary_name),
        verifier_binary_name = json_escape(verifier_binary_name),
        build_identity = json_escape(&build_identity),
        distribution = DISTRIBUTION,
        native_product_version = NATIVE_PRODUCT_VERSION,
        package_version = PACKAGE_VERSION,
        target = json_escape(&target),
    );
    fs::write(out_dir.join("native-core-manifest.json"), manifest)
        .expect("failed to write native compiler-core manifest");
}

fn stage_executable(source: &Path, destination: &Path, description: &str) {
    assert!(
        source.is_file(),
        "{description} was not produced at {}",
        source.display()
    );
    fs::copy(source, destination).unwrap_or_else(|error| {
        panic!(
            "failed to stage {description} {}: {error}",
            source.display()
        )
    });
    preserve_executable_mode(source, destination);
}

fn build_native_binary(
    workspace: &Path,
    out_dir: &Path,
    target: &str,
    profile: &str,
    build_identity: &str,
    executable: &NativeBinary<'_>,
) -> PathBuf {
    // A nested Cargo process cannot use a target directory below the outer
    // Cargo target: the parent build holds that directory lock. Use the OS
    // temporary area and a stable build-unit key so repeated builds can cache.
    let build_unit = out_dir
        .ancestors()
        .nth(2)
        .and_then(Path::file_name)
        .and_then(|value| value.to_str())
        .unwrap_or("aether-python");
    let nested_target = env::temp_dir()
        .join("aether-compiler-core-build")
        .join(build_unit)
        .join("companion-target");
    let mut command = Command::new(required_env("CARGO"));
    command
        .arg("build")
        .arg("--manifest-path")
        .arg(workspace.join("Cargo.toml"))
        .arg("--locked")
        .arg("--package")
        .arg(executable.package)
        .arg("--bin")
        .arg(executable.binary)
        .arg("--target")
        .arg(target)
        .arg("--target-dir")
        .arg(&nested_target)
        .env("AETHER_COMPILER_CORE_BUILD_IDENTITY", build_identity);
    if profile == "release" {
        command.arg("--release");
    }
    let status = command
        .status()
        .expect("failed to launch Cargo for a native compiler-core executable");
    assert!(
        status.success(),
        "Cargo failed while building a native compiler-core executable"
    );
    nested_target
        .join(target)
        .join(profile)
        .join(executable.file_name)
}

fn repository_identity(repository: &Path) -> String {
    let output = Command::new("git")
        .arg("-C")
        .arg(repository)
        .arg("rev-parse")
        .arg("HEAD")
        .output();
    match output {
        Ok(output) if output.status.success() => {
            String::from_utf8_lossy(&output.stdout).trim().to_owned()
        }
        _ => "source-build-unknown-revision".to_owned(),
    }
}

fn required_env(name: &str) -> String {
    env::var(name).unwrap_or_else(|_| panic!("Cargo did not provide {name}"))
}

fn json_escape(value: &str) -> String {
    value
        .replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

#[cfg(unix)]
fn preserve_executable_mode(source: &Path, destination: &Path) {
    use std::os::unix::fs::PermissionsExt;
    let mode = fs::metadata(source)
        .expect("failed to inspect companion permissions")
        .permissions()
        .mode();
    let mut permissions = fs::metadata(destination)
        .expect("failed to inspect staged companion permissions")
        .permissions();
    permissions.set_mode(mode | 0o755);
    fs::set_permissions(destination, permissions)
        .expect("failed to preserve companion executable permissions");
}

#[cfg(not(unix))]
fn preserve_executable_mode(_source: &Path, _destination: &Path) {}
