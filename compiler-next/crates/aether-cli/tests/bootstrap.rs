//! End-to-end qualification of the official CLI.

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
    Command::new(env!("CARGO_BIN_EXE_aether"))
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
fn compiler_selector_is_not_part_of_the_official_cli() {
    let directory = Directory::new("compiler-selector");
    directory.write("main.ae", "int main(){return 0;}");
    for arguments in [
        vec!["--compiler", "next", "run", "main.ae"],
        vec!["--compiler", "legacy", "run", "main.ae"],
        vec!["run", "main.ae", "--compiler=next"],
        vec!["run", "main.ae", "--compiler=legacy"],
    ] {
        let output = cli(&directory, &arguments);
        assert_eq!(output.status.code(), Some(2), "{arguments:?}");
        assert!(String::from_utf8_lossy(&output.stderr).contains("unknown option"));
    }
}

#[test]
fn packaging_has_one_owner_for_each_public_cli_name() {
    let cargo = include_str!("../Cargo.toml");
    assert!(cargo.contains("name = \"aether\""));
    assert!(!cargo.contains("name = \"aether-cli-next\""));

    let repository = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let python = fs::read_to_string(repository.join("pyproject.toml")).unwrap();
    assert!(python.contains("aether-legacy = \"aether.cli:main\""));
    assert!(
        !python
            .lines()
            .any(|line| line == "aether = \"aether.cli:main\"")
    );
}

#[test]
fn official_cli_does_not_shell_out_to_an_aether_cli() {
    let source = include_str!("../src/lib.rs");
    assert!(!source.contains("Command::new"));
    assert!(!source.contains("aether-next"));
    assert!(!source.contains("aether-legacy"));
}

#[test]
fn official_name_reaches_compiler_next_authority() {
    let directory = Directory::new("compiler-next-authority");
    directory.write(
        "default-parameter.ae",
        "int add(int value, int increment = 2){return value+increment;}\nint main(){return add(40);}",
    );
    let output = cli(&directory, &["check", "default-parameter.ae"]);
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
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
fn main_fallback_works_and_registry_dependencies_fail_explicitly() {
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
    assert!(String::from_utf8_lossy(&rejected.stderr).contains("run `aether update`"));
}

#[test]
fn path_dependencies_are_recursive_owner_scoped_and_canonical() {
    let directory = Directory::new("path-graph");
    directory.write("app/aether.toml", "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\na={path='../a'}\nb={path='../b'}\n");
    directory.write(
        "app/src/main.ae",
        "import a; import b; int main(){return a.answer()+b.answer()-42;}",
    );
    directory.write(
        "a/aether.toml",
        "[package]\nname='a'\nversion='1.0.0'\n[dependencies]\nmath={path='../math-v1'}\n",
    );
    directory.write(
        "a/src/lib.ae",
        "package a; import math; int answer(){math.Record v=math.make(20);return v.value;}",
    );
    directory.write("b/aether.toml", "[package]\nname='b'\nversion='1.0.0'\n[dependencies]\nmath={path='../math-v2/../math-v2'}\n");
    directory.write(
        "b/src/lib.ae",
        "package b; import math; int answer(){math.Record v=math.make(22);return v.value;}",
    );
    directory.write(
        "math-v1/aether.toml",
        "[package]\nname='math'\nversion='1.5.0'\n",
    );
    directory.write(
        "math-v1/src/lib.ae",
        "package math; struct Record{int value;} Record make(int x){return Record(x);}",
    );
    directory.write(
        "math-v2/aether.toml",
        "[package]\nname='math'\nversion='2.1.0'\n",
    );
    directory.write(
        "math-v2/src/lib.ae",
        "package math; struct Record{int value;} Record make(int x){return Record(x);}",
    );

    for optimization in ["-O0", "-O2"] {
        let checked = cli(&directory, &["check", "app", optimization]);
        assert!(
            checked.status.success(),
            "{}",
            String::from_utf8_lossy(&checked.stderr)
        );
        let ran = cli(&directory, &["run", "app", optimization]);
        assert_eq!(
            ran.status.code(),
            Some(0),
            "{}",
            String::from_utf8_lossy(&ran.stderr)
        );
    }
}

#[test]
fn cross_version_nominal_types_do_not_mix() {
    let directory = Directory::new("path-nominal");
    directory.write("app/aether.toml", "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\na={path='../a'}\nb={path='../b'}\n");
    directory.write(
        "app/src/main.ae",
        "import a; import b; int main(){return b.consume(a.make());}",
    );
    directory.write(
        "a/aether.toml",
        "[package]\nname='a'\nversion='1.0.0'\n[dependencies]\nmath={path='../math1'}\n",
    );
    directory.write(
        "a/src/lib.ae",
        "package a; import math; math.Record make(){return math.Record(1);}",
    );
    directory.write(
        "b/aether.toml",
        "[package]\nname='b'\nversion='1.0.0'\n[dependencies]\nmath={path='../math2'}\n",
    );
    directory.write(
        "b/src/lib.ae",
        "package b; import math; int consume(math.Record value){return value.x;}",
    );
    directory.write(
        "math1/aether.toml",
        "[package]\nname='math'\nversion='1.0.0'\n",
    );
    directory.write("math1/src/lib.ae", "package math; struct Record{int x;}");
    directory.write(
        "math2/aether.toml",
        "[package]\nname='math'\nversion='2.0.0'\n",
    );
    directory.write("math2/src/lib.ae", "package math; struct Record{int x;}");

    let rejected = cli(&directory, &["check", "app"]);
    assert_eq!(rejected.status.code(), Some(1));
    assert!(
        String::from_utf8_lossy(&rejected.stderr).contains("argument"),
        "{}",
        String::from_utf8_lossy(&rejected.stderr)
    );
}

#[test]
fn path_dependency_validation_reports_name_missing_manifest_and_cycles() {
    let directory = Directory::new("path-errors");
    directory.write("app/src/main.ae", "int main(){return 0;}");
    directory.write(
        "wrong/aether.toml",
        "[package]\nname='actual'\nversion='1.0.0'\n",
    );
    directory.write("wrong/src/lib.ae", "package actual;");
    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nexpected={path='../wrong'}\n",
    );
    let mismatch = cli(&directory, &["check", "app"]);
    assert!(String::from_utf8_lossy(&mismatch.stderr).contains("does not match package.name"));

    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\nmissing={path='../missing'}\n",
    );
    directory.write("missing/README", "no manifest here");
    let missing = cli(&directory, &["check", "app"]);
    assert!(String::from_utf8_lossy(&missing.stderr).contains("requires direct `aether.toml`"));

    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\na={path='../a'}\n",
    );
    directory.write(
        "a/aether.toml",
        "[package]\nname='a'\nversion='1.0.0'\n[dependencies]\napp={path='../app/./'}\n",
    );
    directory.write("a/src/lib.ae", "package a;");
    let cycle = cli(&directory, &["check", "app"]);
    assert!(
        String::from_utf8_lossy(&cycle.stderr).contains("path dependency cycle: app -> a -> app")
    );
}

#[test]
fn transitive_dependency_is_not_visible_without_a_direct_edge() {
    let directory = Directory::new("path-no-leak");
    directory.write(
        "app/aether.toml",
        "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\na={path='../a'}\n",
    );
    directory.write(
        "app/src/main.ae",
        "import hidden; int main(){return hidden.value();}",
    );
    directory.write(
        "a/aether.toml",
        "[package]\nname='a'\nversion='1.0.0'\n[dependencies]\nhidden={path='../hidden'}\n",
    );
    directory.write(
        "a/src/lib.ae",
        "package a; import hidden; int value(){return hidden.value();}",
    );
    directory.write(
        "hidden/aether.toml",
        "[package]\nname='hidden'\nversion='1.0.0'\n",
    );
    directory.write(
        "hidden/src/lib.ae",
        "package hidden; int value(){return 1;}",
    );
    let rejected = cli(&directory, &["check", "app"]);
    assert_eq!(rejected.status.code(), Some(1));
    assert!(
        String::from_utf8_lossy(&rejected.stderr)
            .contains("does not declare direct dependency `hidden`")
    );
}

#[cfg(unix)]
#[test]
fn diamond_and_symlink_spellings_share_one_canonical_package_instance() {
    use std::os::unix::fs::symlink;

    let directory = Directory::new("path-diamond-symlink");
    directory.write("app/aether.toml", "[package]\nname='app'\nversion='0.1.0'\n[dependencies]\na={path='../a'}\nb={path='../b'}\n");
    directory.write(
        "app/src/main.ae",
        "import a; import b; int main(){return a.value()+b.value()-2;}",
    );
    directory.write(
        "a/aether.toml",
        "[package]\nname='a'\nversion='1.0.0'\n[dependencies]\ncommon={path='../common'}\n",
    );
    directory.write(
        "a/src/lib.ae",
        "package a; import common; int value(){return common.value();}",
    );
    directory.write(
        "b/aether.toml",
        "[package]\nname='b'\nversion='1.0.0'\n[dependencies]\ncommon={path='../common-link'}\n",
    );
    directory.write(
        "b/src/lib.ae",
        "package b; import common; int value(){return common.value();}",
    );
    directory.write(
        "common/aether.toml",
        "[package]\nname='common'\nversion='1.0.0'\n",
    );
    directory.write(
        "common/src/lib.ae",
        "package common; int value(){return 1;}",
    );
    symlink(directory.0.join("common"), directory.0.join("common-link")).unwrap();

    let output = cli(&directory, &["run", "app"]);
    assert_eq!(
        output.status.code(),
        Some(0),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
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
