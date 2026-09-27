//! End-to-end qualification of the development-name CLI.

use std::fs;
use std::path::PathBuf;
use std::process::{Command, Output};

struct Directory(PathBuf);

impl Directory {
    fn new(label: &str) -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-cli-v1-e2e-{label}-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }

    fn write(&self, name: &str, text: &str) -> PathBuf {
        let path = self.0.join(name);
        fs::write(&path, text).unwrap();
        path
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn cli(directory: &Directory, arguments: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_aether-cli-next"))
        .args(arguments)
        .current_dir(&directory.0)
        .output()
        .unwrap()
}

#[test]
fn usage_and_target_errors_exit_two() {
    let directory = Directory::new("usage");
    directory.write("wrong.txt", "int main(){return 0;}");
    for arguments in [
        vec!["run"],
        vec!["build"],
        vec!["check"],
        vec!["run", "one.ae", "two.ae"],
        vec!["run", "missing.ae"],
        vec!["run", "wrong.txt"],
        vec!["run", "."],
        vec!["build", "one.ae", "--"],
        vec!["check", "one.ae", "--", "arg"],
    ] {
        let output = cli(&directory, &arguments);
        assert_eq!(output.status.code(), Some(2), "{arguments:?}");
        assert!(!output.stderr.is_empty(), "{arguments:?}");
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn file_operations_ignore_neighbor_manifest_and_handle_spaces() {
    let directory = Directory::new("manifest");
    directory.write("aether.toml", "this is deliberately invalid = [");
    directory.write("space name.ae", "int main(){return 0;}");

    for optimization in ["-O0", "-O2"] {
        let checked = cli(&directory, &["check", "space name.ae", optimization]);
        assert!(
            checked.status.success(),
            "{}",
            String::from_utf8_lossy(&checked.stderr)
        );

        let artifact = format!("built-{optimization}");
        let built = cli(
            &directory,
            &["build", "space name.ae", optimization, "-o", &artifact],
        );
        assert!(
            built.status.success(),
            "{}",
            String::from_utf8_lossy(&built.stderr)
        );
        assert!(directory.0.join(&artifact).is_file());

        let ran = cli(&directory, &["run", "space name.ae", optimization]);
        assert!(
            ran.status.success(),
            "{}",
            String::from_utf8_lossy(&ran.stderr)
        );
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn shorthand_and_run_forward_exact_tail_and_propagate_status() {
    let directory = Directory::new("argv");
    directory.write(
        "args.ae",
        r#"import std.Process;
int main(){
  Array<string> args=std.Process.args();
  if(length(args)!=4){return 10;}
  if(args[0]!="arg1"){return 11;}
  if(args[1]!="-x"){return 12;}
  if(args[2]!="--"){return 13;}
  if(args[3]!="arg2"){return 14;}
  return 0;
}"#,
    );
    for arguments in [
        vec!["run", "args.ae", "--", "arg1", "-x", "--", "arg2"],
        vec!["args.ae", "--", "arg1", "-x", "--", "arg2"],
    ] {
        let output = cli(&directory, &arguments);
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
    }

    directory.write("status.ae", "int main(){return 37;}");
    assert_eq!(
        cli(&directory, &["run", "status.ae"]).status.code(),
        Some(37)
    );
    assert_eq!(cli(&directory, &["status.ae"]).status.code(), Some(37));
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn check_creates_no_default_executable_while_build_does() {
    let directory = Directory::new("artifact");
    directory.write("main.ae", "int main(){return 0;}");
    assert!(cli(&directory, &["check", "main.ae"]).status.success());
    assert!(!directory.0.join("main").exists());
    assert!(cli(&directory, &["build", "main.ae"]).status.success());
    assert!(directory.0.join("main").is_file());
}
