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
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent).unwrap();
        }
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

fn manifest(name: &str) -> String {
    format!("[package]\nname = {name:?}\nversion = \"0.1.0\"\n")
}

#[test]
fn project_resolution_is_exact_and_manifests_are_strict() {
    let directory = Directory::new("project-resolution");
    directory.write("aether.toml", &manifest("parent"));
    directory.write("src/main.ae", "int main(){return 0;}");
    fs::create_dir(directory.0.join("child")).unwrap();
    let no_ancestor = cli(&directory, &["check", "child"]);
    assert_eq!(no_ancestor.status.code(), Some(2));

    let descendant = directory.0.join("outer/nested");
    fs::create_dir_all(descendant.join("src")).unwrap();
    fs::write(descendant.join("aether.toml"), manifest("nested")).unwrap();
    fs::write(descendant.join("src/main.ae"), "int main(){return 0;}").unwrap();
    assert_eq!(cli(&directory, &["check", "outer"]).status.code(), Some(2));

    for (manifest_text, expected) in [
        ("not = [", "invalid manifest"),
        (
            "[package]\nname='ok'\nversion='0.1.0'\nextra=1\n",
            "unknown field",
        ),
        (
            "[package]\nname='bad-name'\nversion='0.1.0'\n",
            "namespace identifier",
        ),
        ("[package]\nname='ok'\nversion='v1'\n", "SemVer"),
    ] {
        let project = directory
            .0
            .join(format!("bad-{}", expected.replace(' ', "-")));
        fs::create_dir_all(project.join("src")).unwrap();
        fs::write(project.join("aether.toml"), manifest_text).unwrap();
        fs::write(project.join("src/main.ae"), "int main(){return 0;}").unwrap();
        let output = cli(&directory, &["check", project.to_str().unwrap()]);
        assert_eq!(output.status.code(), Some(2));
        assert!(String::from_utf8_lossy(&output.stderr).contains(expected));
    }
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn application_project_entry_outputs_forwarding_and_optimization() {
    let directory = Directory::new("project-app");
    directory.write(
        "app/aether.toml",
        "[package]\nname='myApp'\nversion='1.2.3'\naether='1'\n\n[application]\nentry='code/start.ae'\n",
    );
    directory.write(
        "app/code/start.ae",
        "import std.Process; int main(){Array<string>a=std.Process.args();if(length(a)!=1){return 9;}if(a[0]!=\"ok\"){return 8;}return 0;}",
    );
    for optimization in ["-O0", "-O2"] {
        let checked = cli(&directory, &["check", "app", optimization]);
        assert!(
            checked.status.success(),
            "{}",
            String::from_utf8_lossy(&checked.stderr)
        );
        let run = cli(&directory, &["run", "app", optimization, "--", "ok"]);
        assert!(
            run.status.success(),
            "{}",
            String::from_utf8_lossy(&run.stderr)
        );
    }
    let built = cli(&directory, &["build", "app"]);
    assert!(
        built.status.success(),
        "{}",
        String::from_utf8_lossy(&built.stderr)
    );
    assert!(directory.0.join("app/.aether/build/myApp").is_file());
    assert!(!directory.0.join("app/code/start").exists());
}

#[test]
#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
fn library_classification_and_bootstrap_artifact() {
    let directory = Directory::new("project-lib");
    directory.write("lib/aether.toml", &manifest("myLibrary"));
    directory.write("lib/src/lib.ae", "int answer(){return 42;}");
    assert!(cli(&directory, &["check", "lib"]).status.success());
    let built = cli(&directory, &["build", "lib"]);
    assert!(
        built.status.success(),
        "{}",
        String::from_utf8_lossy(&built.stderr)
    );
    assert!(
        directory
            .0
            .join("lib/.aether/build/myLibrary.aetherlib")
            .is_file()
    );
    assert_eq!(cli(&directory, &["run", "lib"]).status.code(), Some(2));

    directory.write("lib/src/main.ae", "int main(){return 0;}");
    assert_eq!(cli(&directory, &["check", "lib"]).status.code(), Some(2));
    fs::remove_file(directory.0.join("lib/src/main.ae")).unwrap();
    fs::remove_file(directory.0.join("lib/src/lib.ae")).unwrap();
    assert_eq!(cli(&directory, &["check", "lib"]).status.code(), Some(2));
}

#[test]
fn explicit_entry_never_falls_back_and_cannot_escape() {
    let directory = Directory::new("entry-errors");
    directory.write("outside.ae", "int main(){return 0;}");
    directory.write("app/src/main.ae", "int main(){return 0;}");
    for entry in [
        "missing.ae",
        "../outside.ae",
        "/tmp/outside.ae",
        "src/main.txt",
    ] {
        directory.write(
            "app/aether.toml",
            &format!("{}\n[application]\nentry={entry:?}\n", manifest("app")),
        );
        assert_eq!(
            cli(&directory, &["check", "app"]).status.code(),
            Some(2),
            "{entry}"
        );
    }
}

#[test]
fn main_fallback_works_and_dependencies_fail_explicitly() {
    let directory = Directory::new("fallback-dependencies");
    directory.write("app/aether.toml", &manifest("app"));
    directory.write("app/src/main.ae", "int main(){return 0;}");
    assert!(cli(&directory, &["check", "app"]).status.success());

    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nother='1.2'\n",
    );
    let rejected = cli(&directory, &["check", "app"]);
    assert_eq!(rejected.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&rejected.stderr).contains("resolution is not supported"));
}

#[test]
fn init_application_library_and_no_overwrite() {
    let directory = Directory::new("init");
    assert!(cli(&directory, &["init", "myProject"]).status.success());
    assert!(directory.0.join("myProject/aether.toml").is_file());
    assert!(directory.0.join("myProject/src/main.ae").is_file());
    assert!(
        cli(&directory, &["init", "--lib", "myLibrary"])
            .status
            .success()
    );
    assert!(directory.0.join("myLibrary/src/lib.ae").is_file());
    let before = fs::read_to_string(directory.0.join("myProject/aether.toml")).unwrap();
    assert_eq!(
        cli(&directory, &["init", "myProject"]).status.code(),
        Some(2)
    );
    assert_eq!(
        fs::read_to_string(directory.0.join("myProject/aether.toml")).unwrap(),
        before
    );
    assert_eq!(
        cli(&directory, &["init", "bad-name"]).status.code(),
        Some(2)
    );
    assert!(!directory.0.join("bad-name").exists());
}
