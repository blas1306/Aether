//! FILE-ATOMIC-WRITE-V1 POSIX/Linux qualification.

use std::fs;
use std::os::unix::fs::{MetadataExt, PermissionsExt, symlink};
use std::os::unix::process::ExitStatusExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use aether_driver::{
    ClangToolchain, Emit, OptimizationLevel, build_path, compile_source_with_optimization,
};
use aether_frontend::{CallSiteId, SourceFile, analyze, parse_source};
use aether_middle::{Rvalue, SsaOp, build_ssa, lower_hir, verify_mir, verify_ssa};

struct Directory(PathBuf);

impl Directory {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let path = std::env::temp_dir().join(format!(
            "aether-file-atomic-v1-{}-{}",
            std::process::id(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        fs::create_dir(&path).unwrap();
        Self(path)
    }
}

impl Drop for Directory {
    fn drop(&mut self) {
        let _ = fs::set_permissions(&self.0, fs::Permissions::from_mode(0o700));
        fs::remove_dir_all(&self.0).unwrap();
    }
}

fn build(
    directory: &Directory,
    source: &str,
    optimization: OptimizationLevel,
) -> (aether_driver::Compilation, PathBuf) {
    static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    let input = directory.0.join("main.ae");
    let executable = directory.0.join(format!(
        "program-{optimization:?}-{}",
        NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
    ));
    fs::write(&input, source).unwrap();
    let compilation = build_path(
        &input,
        &executable,
        &[Emit::Hir, Emit::Mir, Emit::Ssa, Emit::Llvm],
        &ClangToolchain::default().with_optimization(optimization),
    )
    .unwrap_or_else(|errors| panic!("{source}\n{errors:#?}"));
    (compilation, executable)
}

fn run(executable: &Path) -> std::process::Output {
    Command::new(executable).output().unwrap()
}

fn execute_llvm(directory: &Directory, llvm: &str) -> std::process::Output {
    let input = directory.0.join("injected.ll");
    let executable = directory.0.join("injected");
    fs::write(&input, llvm).unwrap();
    let linked = Command::new("clang")
        .args(["-Wno-override-module", "-O0", "-x", "ir"])
        .arg(&input)
        .arg("-o")
        .arg(&executable)
        .arg("-lstdc++")
        .output()
        .unwrap();
    assert!(
        linked.status.success(),
        "{}",
        String::from_utf8_lossy(&linked.stderr)
    );
    run(&executable)
}

fn atomic_source(path: &Path, value: &str) -> String {
    let value = value
        .replace('\\', "\\\\")
        .replace('\0', "\\0")
        .replace('\r', "\\r")
        .replace('\n', "\\n")
        .replace('"', "\\\"");
    format!(
        "package main;import std.File;int main(){{string path=\"{}\";string value=\"{value}\";std.File.writeTextAtomic(&path,&value);return 0;}}",
        path.display()
    )
}

fn private_temps(directory: &Path) -> Vec<PathBuf> {
    fs::read_dir(directory)
        .unwrap()
        .map(|entry| entry.unwrap().path())
        .filter(|path| {
            path.file_name()
                .unwrap()
                .to_string_lossy()
                .starts_with(".aether-write-")
        })
        .collect()
}

#[test]
fn exact_bytes_replace_symlink_and_new_metadata_work_at_o0_o2() {
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let directory = Directory::new();
        let target = directory.0.join("ledger.txt");
        fs::write(&target, b"old-and-longer").unwrap();
        fs::set_permissions(&target, fs::Permissions::from_mode(0o600)).unwrap();
        let old_inode = fs::metadata(&target).unwrap().ino();
        let source = atomic_source(&target, "A\0café🙂\n");
        let (_, executable) = build(&directory, &source, optimization);
        assert_eq!(run(&executable).status.code(), Some(0));
        assert_eq!(fs::read(&target).unwrap(), "A\0café🙂\n".as_bytes());
        assert_ne!(fs::metadata(&target).unwrap().ino(), old_inode);
        assert!(private_temps(&directory.0).is_empty());

        let referent = directory.0.join("referent.txt");
        let link = directory.0.join("link.txt");
        let (_, executable) = build(&directory, &atomic_source(&link, "new"), optimization);
        fs::write(&referent, b"referent").unwrap();
        symlink(&referent, &link).unwrap();
        assert_eq!(run(&executable).status.code(), Some(0));
        assert_eq!(fs::read(&link).unwrap(), b"new");
        assert_eq!(fs::read(&referent).unwrap(), b"referent");
        assert!(
            !fs::symlink_metadata(&link)
                .unwrap()
                .file_type()
                .is_symlink()
        );
    }
}

#[test]
fn empty_large_relative_explicit_parent_and_near_name_max_work() {
    let directory = Directory::new();
    let empty = directory.0.join("empty");
    let (_, executable) = build(
        &directory,
        &atomic_source(&empty, ""),
        OptimizationLevel::O0,
    );
    assert_eq!(run(&executable).status.code(), Some(0));
    assert!(fs::read(&empty).unwrap().is_empty());

    let large = "λ🙂x".repeat(32_768);
    let large_target = directory.0.join("large");
    let (_, executable) = build(
        &directory,
        &atomic_source(&large_target, &large),
        OptimizationLevel::O0,
    );
    assert_eq!(run(&executable).status.code(), Some(0));
    assert_eq!(fs::read(&large_target).unwrap(), large.as_bytes());

    let basename = "n".repeat(250);
    let near_max = directory.0.join(basename);
    let (_, executable) = build(
        &directory,
        &atomic_source(&near_max, "bounded-temp-name"),
        OptimizationLevel::O0,
    );
    assert_eq!(run(&executable).status.code(), Some(0));
    assert_eq!(fs::read(&near_max).unwrap(), b"bounded-temp-name");

    let relative_source = "package main;import std.File;int main(){string path=\"relative\";string value=\"ok\";std.File.writeTextAtomic(&path,&value);return 0;}";
    let (_, executable) = build(&directory, relative_source, OptimizationLevel::O0);
    let status = Command::new(&executable)
        .current_dir(&directory.0)
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(0));
    assert_eq!(fs::read(directory.0.join("relative")).unwrap(), b"ok");
}

#[test]
fn target_directory_and_invalid_paths_are_nominal_io_failures() {
    let directory = Directory::new();
    let target = directory.0.join("target-dir");
    fs::create_dir(&target).unwrap();
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string path=\"{}\";string value=\"x\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.IO.IOException error){{return 0;}}return 3;}}",
        target.display()
    );
    let (_, executable) = build(&directory, &source, OptimizationLevel::O0);
    assert_eq!(run(&executable).status.code(), Some(0));
    assert!(target.is_dir());
    assert!(private_temps(&directory.0).is_empty());

    let missing = directory.0.join("missing-parent").join("target");
    let source = format!(
        "package main;import std.File;int main(){{string path=\"{}\";string value=\"x\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.File.FileNotFoundException error){{return 0;}}return 3;}}",
        missing.display()
    );
    let (_, executable) = build(&directory, &source, OptimizationLevel::O0);
    assert_eq!(run(&executable).status.code(), Some(0));

    for path in ["", "bad\0path"] {
        let source = format!(
            "package main;import std.IO;import std.File;int main(){{string path=\"{path}\";string value=\"x\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.IO.IOException error){{return 0;}}return 3;}}"
        );
        let (_, executable) = build(&directory, &source, OptimizationLevel::O0);
        assert_eq!(run(&executable).status.code(), Some(0));
    }
}

#[test]
fn atomic_runtime_is_reachable_only_from_atomic_write_and_never_links_fsync() {
    let directory = Directory::new();
    let plain = "package main;import std.File;int main(){return 0;}";
    let unused = compile_source_with_optimization(
        &SourceFile::new("unused.ae", plain),
        &[Emit::Llvm],
        OptimizationLevel::O0,
    )
    .unwrap();
    for symbol in [
        "getrandom",
        "openat",
        "renameat",
        "unlinkat",
        "aether_io_write_text_atomic",
    ] {
        assert!(!unused.llvm.contains(symbol));
    }

    let regular =
        atomic_source(&directory.0.join("regular"), "x").replace("writeTextAtomic", "writeText");
    let (regular, _) = build(&directory, &regular, OptimizationLevel::O0);
    for symbol in [
        "getrandom",
        "openat",
        "renameat",
        "unlinkat",
        "aether_io_write_text_atomic",
    ] {
        assert!(!regular.llvm.contains(symbol));
    }

    let (atomic, _) = build(
        &directory,
        &atomic_source(&directory.0.join("atomic"), "x"),
        OptimizationLevel::O0,
    );
    for symbol in ["@getrandom", "@openat", "@renameat", "@unlinkat"] {
        assert!(atomic.llvm.contains(symbol));
    }
    assert!(!atomic.llvm.contains("fsync"));
    for phase in [Emit::Hir, Emit::Mir, Emit::Ssa] {
        let dump = &atomic.dumps[&phase];
        assert!(dump.contains("writeTextAtomic"));
        assert!(dump.contains("Call"));
        assert!(dump.contains("CallScopedSharedBorrow") || phase != Emit::Hir);
        assert!(!dump.contains("FileOp"));
        assert!(!dump.contains("AtomicWriteOp"));
    }
}

#[test]
fn injected_short_write_eintr_zero_progress_and_write_failure_preserve_target() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    fs::write(&target, b"old").unwrap();
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string path=\"{}\";string value=\"abcdef\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.IO.IOException error){{return 7;}}return 0;}}",
        target.display()
    );
    let (compilation, _) = build(&directory, &source, OptimizationLevel::O0);
    let renamed = compilation
        .llvm
        .replace("@write(", "@aether_test_write(")
        .replace("declare i64 @aether_test_write(i32, ptr, i64)\n", "");
    let short = format!(
        "{renamed}\ndeclare i64 @write(i32, ptr, i64)\n@calls = internal global i64 0\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{\nentry:\n  %n = load i64, ptr @calls\n  %next = add i64 %n, 1\n  store i64 %next, ptr @calls\n  %first = icmp eq i64 %n, 0\n  br i1 %first, label %eintr, label %do\neintr:\n  %ep = call ptr @__errno_location()\n  store i32 4, ptr %ep\n  ret i64 -1\ndo:\n  %long = icmp ugt i64 %length, 1\n  %amount = select i1 %long, i64 1, i64 %length\n  %r = call i64 @write(i32 %fd, ptr %data, i64 %amount)\n  ret i64 %r\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &short).status.code(), Some(0));
    assert_eq!(fs::read(&target).unwrap(), b"abcdef");

    fs::write(&target, b"old").unwrap();
    let zero = format!(
        "{renamed}\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{ ret i64 0 }}\n"
    );
    assert_eq!(execute_llvm(&directory, &zero).status.code(), Some(7));
    assert_eq!(fs::read(&target).unwrap(), b"old");
    assert!(private_temps(&directory.0).is_empty());

    fs::write(&target, b"old").unwrap();
    let fail = format!(
        "{renamed}\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i64 -1\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &fail).status.code(), Some(7));
    assert_eq!(fs::read(&target).unwrap(), b"old");
    assert!(private_temps(&directory.0).is_empty());

    for fail_at in 1..=6 {
        fs::write(&target, b"old").unwrap();
        let prefix_failure = format!(
            "{renamed}\ndeclare i64 @write(i32, ptr, i64)\n@prefix_calls_{fail_at} = internal global i64 0\ndefine i64 @aether_test_write(i32 %fd, ptr %data, i64 %length) {{\nentry:\n  %n = load i64, ptr @prefix_calls_{fail_at}\n  %fail = icmp eq i64 %n, {fail_at}\n  br i1 %fail, label %error, label %one\none:\n  %next = add i64 %n, 1\n  store i64 %next, ptr @prefix_calls_{fail_at}\n  %r = call i64 @write(i32 %fd, ptr %data, i64 1)\n  ret i64 %r\nerror:\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i64 -1\n}}\n"
        );
        let output = execute_llvm(&directory, &prefix_failure);
        if fail_at < 6 {
            assert_eq!(output.status.code(), Some(7), "fail_at={fail_at}");
            assert_eq!(fs::read(&target).unwrap(), b"old");
        } else {
            assert_eq!(output.status.code(), Some(0));
            assert_eq!(fs::read(&target).unwrap(), b"abcdef");
        }
        assert!(private_temps(&directory.0).is_empty());
    }
}

#[test]
fn repeated_overwrite_publishes_each_complete_value() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    let source = format!(
        "package main;import std.File;int main(){{string path=\"{}\";string a=\"first-long-value\";string b=\"x\";string c=\"third\";std.File.writeTextAtomic(&path,&a);std.File.writeTextAtomic(&path,&b);std.File.writeTextAtomic(&path,&c);return 0;}}",
        target.display()
    );
    for optimization in [OptimizationLevel::O0, OptimizationLevel::O2] {
        let (_, executable) = build(&directory, &source, optimization);
        assert_eq!(run(&executable).status.code(), Some(0));
        assert_eq!(fs::read(&target).unwrap(), b"third");
        assert!(private_temps(&directory.0).is_empty());
    }
}

#[test]
fn injected_rename_failure_is_not_retried_and_cleanup_error_cannot_mask_primary() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    fs::write(&target, b"old").unwrap();
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string path=\"{}\";string value=\"new\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.File.PermissionDeniedException error){{return 4;}}catch(std.IO.IOException error){{return 7;}}return 0;}}",
        target.display()
    );
    let (compilation, _) = build(&directory, &source, OptimizationLevel::O0);
    let renamed = compilation
        .llvm
        .replace("@renameat(", "@aether_test_renameat(")
        .replace("@unlinkat(", "@aether_test_unlinkat(")
        .replace(
            "declare i32 @aether_test_renameat(i32, ptr, i32, ptr)\n",
            "",
        )
        .replace("declare i32 @aether_test_unlinkat(i32, ptr, i32)\n", "");
    let injected = format!(
        "{renamed}\n@rename_calls = internal global i32 0\ndefine i32 @aether_test_renameat(i32 %a, ptr %b, i32 %c, ptr %d) {{\n  %n = load i32, ptr @rename_calls\n  %next = add i32 %n, 1\n  store i32 %next, ptr @rename_calls\n  %ep = call ptr @__errno_location()\n  store i32 13, ptr %ep\n  ret i32 -1\n}}\ndefine i32 @aether_test_unlinkat(i32 %a, ptr %b, i32 %c) {{\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i32 -1\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &injected).status.code(), Some(4));
    assert_eq!(fs::read(&target).unwrap(), b"old");
    assert_eq!(private_temps(&directory.0).len(), 1);
}

#[test]
fn concurrent_writers_and_observer_only_see_complete_versions() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    let old = "O".repeat(65_536);
    let left = "L".repeat(65_536);
    let right = "R".repeat(65_536);
    fs::write(&target, &old).unwrap();
    let (_, left_exe) = build(
        &directory,
        &atomic_source(&target, &left),
        OptimizationLevel::O2,
    );
    let (_, right_exe) = build(
        &directory,
        &atomic_source(&target, &right),
        OptimizationLevel::O2,
    );
    let mut a = Command::new(left_exe)
        .stdout(Stdio::null())
        .spawn()
        .unwrap();
    let mut b = Command::new(right_exe)
        .stdout(Stdio::null())
        .spawn()
        .unwrap();
    while a.try_wait().unwrap().is_none() || b.try_wait().unwrap().is_none() {
        let observed = fs::read(&target).unwrap();
        assert!(
            observed == old.as_bytes()
                || observed == left.as_bytes()
                || observed == right.as_bytes()
        );
    }
    let final_bytes = fs::read(&target).unwrap();
    assert!(final_bytes == left.as_bytes() || final_bytes == right.as_bytes());
    assert!(private_temps(&directory.0).is_empty());
}

#[test]
fn umask_controls_new_mode_and_replacement_does_not_preserve_metadata() {
    let directory = Directory::new();
    let target = directory.0.join("mode-target");
    fs::write(&target, b"old").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o600)).unwrap();
    let old_inode = fs::metadata(&target).unwrap().ino();
    let (_, executable) = build(
        &directory,
        &atomic_source(&target, "new"),
        OptimizationLevel::O0,
    );
    let status = Command::new("sh")
        .args(["-c", "umask 027; exec \"$1\"", "sh"])
        .arg(&executable)
        .status()
        .unwrap();
    assert_eq!(status.code(), Some(0));
    let metadata = fs::metadata(&target).unwrap();
    assert_eq!(metadata.permissions().mode() & 0o777, 0o640);
    assert_ne!(metadata.ino(), old_inode);
}

#[test]
fn injected_entropy_parent_create_and_close_failures_are_pre_publish() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    fs::write(&target, b"old").unwrap();
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string path=\"{}\";string value=\"new\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.File.PermissionDeniedException error){{return 4;}}catch(std.IO.IOException error){{return 7;}}return 0;}}",
        target.display()
    );
    let (compilation, _) = build(&directory, &source, OptimizationLevel::O0);

    let entropy_ir = compilation
        .llvm
        .replace("@getrandom(", "@aether_test_getrandom(")
        .replace("declare i64 @aether_test_getrandom(ptr, i64, i32)\n", "");
    let entropy_ir = format!(
        "{entropy_ir}\ndefine i64 @aether_test_getrandom(ptr %p, i64 %n, i32 %f) {{\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i64 -1\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &entropy_ir).status.code(), Some(7));
    assert_eq!(fs::read(&target).unwrap(), b"old");
    assert!(private_temps(&directory.0).is_empty());

    let parent_ir = compilation
        .llvm
        .replace("@open(", "@aether_test_open(")
        .replace("declare i32 @aether_test_open(ptr, i32, ...)\n", "");
    let parent_ir = format!(
        "{parent_ir}\ndefine i32 @aether_test_open(ptr %p, i32 %f, ...) {{\n  %ep = call ptr @__errno_location()\n  store i32 13, ptr %ep\n  ret i32 -1\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &parent_ir).status.code(), Some(4));
    assert_eq!(fs::read(&target).unwrap(), b"old");

    let create_ir = compilation
        .llvm
        .replace("@openat(", "@aether_test_openat(")
        .replace("declare i32 @aether_test_openat(i32, ptr, i32, ...)\n", "");
    let create_ir = format!(
        "{create_ir}\ndefine i32 @aether_test_openat(i32 %d, ptr %p, i32 %f, ...) {{\n  %ep = call ptr @__errno_location()\n  store i32 13, ptr %ep\n  ret i32 -1\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &create_ir).status.code(), Some(4));
    assert_eq!(fs::read(&target).unwrap(), b"old");

    let close_ir = compilation
        .llvm
        .replace("@close(", "@aether_test_close(")
        .replace("declare i32 @aether_test_close(i32)\n", "");
    let close_ir = format!(
        "{close_ir}\ndeclare i32 @close(i32)\n@close_calls = internal global i32 0\ndefine i32 @aether_test_close(i32 %fd) {{\n  %n = load i32, ptr @close_calls\n  %next = add i32 %n, 1\n  store i32 %next, ptr @close_calls\n  %first = icmp eq i32 %n, 0\n  br i1 %first, label %fail, label %real\nfail:\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i32 -1\nreal:\n  %r = call i32 @close(i32 %fd)\n  ret i32 %r\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &close_ir).status.code(), Some(7));
    assert_eq!(fs::read(&target).unwrap(), b"old");
    assert!(private_temps(&directory.0).is_empty());
}

#[test]
fn collision_and_candidate_equal_target_are_bounded_and_never_open_existing_entry() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    let source = atomic_source(&target, "new");
    let (compilation, _) = build(&directory, &source, OptimizationLevel::O0);
    let collision_ir = compilation
        .llvm
        .replace("@openat(", "@aether_test_openat(")
        .replace("declare i32 @aether_test_openat(i32, ptr, i32, ...)\n", "");
    let collision_ir = format!(
        "{collision_ir}\ndeclare i32 @openat(i32, ptr, i32, ...)\n@openat_calls = internal global i32 0\ndefine i32 @aether_test_openat(i32 %d, ptr %p, i32 %f, ...) {{\n  %n = load i32, ptr @openat_calls\n  %next = add i32 %n, 1\n  store i32 %next, ptr @openat_calls\n  %first = icmp eq i32 %n, 0\n  br i1 %first, label %collision, label %real\ncollision:\n  %ep = call ptr @__errno_location()\n  store i32 17, ptr %ep\n  ret i32 -1\nreal:\n  %r = call i32 (i32, ptr, i32, ...) @openat(i32 %d, ptr %p, i32 %f, i32 438)\n  ret i32 %r\n}}\n"
    );
    assert_eq!(
        execute_llvm(&directory, &collision_ir).status.code(),
        Some(0)
    );
    assert_eq!(fs::read(&target).unwrap(), b"new");

    let equal_target = directory
        .0
        .join(".aether-write-00000000000000000000000000000000");
    fs::write(&equal_target, b"old").unwrap();
    let (compilation, _) = build(
        &directory,
        &atomic_source(&equal_target, "new"),
        OptimizationLevel::O0,
    );
    let entropy_ir = compilation
        .llvm
        .replace("@getrandom(", "@aether_test_getrandom(")
        .replace("declare i64 @aether_test_getrandom(ptr, i64, i32)\n", "");
    let entropy_ir = format!(
        "{entropy_ir}\ndefine i64 @aether_test_getrandom(ptr %p, i64 %n, i32 %f) {{\n  store i128 0, ptr %p\n  ret i64 16\n}}\n"
    );
    assert_eq!(
        execute_llvm(&directory, &entropy_ir).status.code(),
        Some(70)
    );
    assert_eq!(fs::read(&equal_target).unwrap(), b"old");
}

#[test]
fn precreated_temp_symlink_is_never_followed_or_truncated() {
    let directory = Directory::new();
    let target = directory.0.join("target");
    let referent = directory.0.join("referent");
    fs::write(&target, b"old").unwrap();
    fs::write(&referent, b"secret").unwrap();
    let candidate = directory
        .0
        .join(".aether-write-00000000000000000000000000000000");
    let (compilation, _) = build(
        &directory,
        &atomic_source(&target, "new"),
        OptimizationLevel::O0,
    );
    symlink(&referent, &candidate).unwrap();
    let entropy_ir = compilation
        .llvm
        .replace("@getrandom(", "@aether_test_getrandom(")
        .replace("declare i64 @aether_test_getrandom(ptr, i64, i32)\n", "");
    let entropy_ir = format!(
        "{entropy_ir}\ndefine i64 @aether_test_getrandom(ptr %p, i64 %n, i32 %f) {{\n  store i128 0, ptr %p\n  ret i64 16\n}}\n"
    );
    assert_eq!(
        execute_llvm(&directory, &entropy_ir).status.code(),
        Some(70)
    );
    assert_eq!(fs::read(&target).unwrap(), b"old");
    assert_eq!(fs::read(&referent).unwrap(), b"secret");
    assert!(
        fs::symlink_metadata(&candidate)
            .unwrap()
            .file_type()
            .is_symlink()
    );
}

#[test]
fn process_kill_before_during_and_after_publish_only_leaves_old_or_new() {
    // Kill immediately before rename: the old target survives and an orphan is allowed.
    let before = Directory::new();
    let before_target = before.0.join("target");
    fs::write(&before_target, b"old").unwrap();
    let (compilation, _) = build(
        &before,
        &atomic_source(&before_target, "new"),
        OptimizationLevel::O0,
    );
    let killed = compilation
        .llvm
        .replace("@renameat(", "@aether_test_renameat(")
        .replace(
            "declare i32 @aether_test_renameat(i32, ptr, i32, ptr)\n",
            "",
        );
    let killed = format!(
        "{killed}\ndeclare i32 @getpid()\ndeclare i32 @kill(i32, i32)\ndefine i32 @aether_test_renameat(i32 %a, ptr %b, i32 %c, ptr %d) {{\n  %pid = call i32 @getpid()\n  %ignored = call i32 @kill(i32 %pid, i32 9)\n  ret i32 -1\n}}\n"
    );
    let output = execute_llvm(&before, &killed);
    assert_eq!(output.status.signal(), Some(9));
    assert_eq!(fs::read(&before_target).unwrap(), b"old");
    assert_eq!(private_temps(&before.0).len(), 1);

    // Kill in the commit wrapper after the kernel accepted rename: new is complete.
    let during = Directory::new();
    let during_target = during.0.join("target");
    fs::write(&during_target, b"old").unwrap();
    let (compilation, _) = build(
        &during,
        &atomic_source(&during_target, "new"),
        OptimizationLevel::O0,
    );
    let killed = compilation
        .llvm
        .replace("@renameat(", "@aether_test_renameat(")
        .replace(
            "declare i32 @aether_test_renameat(i32, ptr, i32, ptr)\n",
            "",
        );
    let killed = format!(
        "{killed}\ndeclare i32 @renameat(i32, ptr, i32, ptr)\ndeclare i32 @getpid()\ndeclare i32 @kill(i32, i32)\ndefine i32 @aether_test_renameat(i32 %a, ptr %b, i32 %c, ptr %d) {{\n  %r = call i32 @renameat(i32 %a, ptr %b, i32 %c, ptr %d)\n  %pid = call i32 @getpid()\n  %ignored = call i32 @kill(i32 %pid, i32 9)\n  ret i32 %r\n}}\n"
    );
    let output = execute_llvm(&during, &killed);
    assert_eq!(output.status.signal(), Some(9));
    assert_eq!(fs::read(&during_target).unwrap(), b"new");
    assert!(private_temps(&during.0).is_empty());

    // Kill in private handle destruction after successful publish: no rollback.
    let after = Directory::new();
    let after_target = after.0.join("target");
    fs::write(&after_target, b"old").unwrap();
    let (compilation, _) = build(
        &after,
        &atomic_source(&after_target, "new"),
        OptimizationLevel::O0,
    );
    let killed = compilation
        .llvm
        .replace("@close(", "@aether_test_close(")
        .replace("declare i32 @aether_test_close(i32)\n", "");
    let killed = format!(
        "{killed}\ndeclare i32 @close(i32)\ndeclare i32 @getpid()\ndeclare i32 @kill(i32, i32)\n@kill_close_calls = internal global i32 0\ndefine i32 @aether_test_close(i32 %fd) {{\n  %r = call i32 @close(i32 %fd)\n  %n = load i32, ptr @kill_close_calls\n  %next = add i32 %n, 1\n  store i32 %next, ptr @kill_close_calls\n  %parent = icmp eq i32 %n, 1\n  br i1 %parent, label %die, label %return\ndie:\n  %pid = call i32 @getpid()\n  %ignored = call i32 @kill(i32 %pid, i32 9)\n  br label %return\nreturn:\n  ret i32 %r\n}}\n"
    );
    let output = execute_llvm(&after, &killed);
    assert_eq!(output.status.signal(), Some(9));
    assert_eq!(fs::read(&after_target).unwrap(), b"new");
    assert!(private_temps(&after.0).is_empty());
}

#[test]
fn atomic_call_shape_preserves_hir_borrows_and_rejects_mir_ssa_unwind_corruption() {
    let source = SourceFile::new(
        "atomic-corruption.ae",
        "package main;import std.File;int main(){string path=\"x\";string value=\"y\";std.File.writeTextAtomic(&path,&value);return 0;}",
    );
    // A standalone SourceFile cannot resolve toolchain modules, so use the
    // ordinary call shape to exercise the same verified call/borrow contract.
    let ordinary = SourceFile::new(
        "ordinary-corruption.ae",
        "void atomicShape(ref string path,ref string value){}int main(){string path=\"x\";string value=\"y\";atomicShape(path,value);return 0;}",
    );
    assert!(parse_source(&source).is_ok());
    let hir = analyze(parse_source(&ordinary).unwrap()).unwrap();
    assert!(hir.dump().contains("CallScopedSharedBorrow"));

    let mir = lower_hir(hir);
    verify_mir(mir.clone()).unwrap();
    let mut bad_borrow = mir.clone();
    let metadata = bad_borrow
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.value {
            Rvalue::Borrow {
                call: Some(metadata),
                ..
            } => Some(metadata),
            _ => None,
        })
        .unwrap();
    metadata.call_site = CallSiteId(metadata.call_site.0 + 100);
    assert!(verify_mir(bad_borrow).is_err());

    let verified = verify_mir(mir).unwrap();
    let ssa = build_ssa(&verified);
    verify_ssa(ssa.clone()).unwrap();
    let mut bad_ssa_borrow = ssa;
    let metadata = bad_ssa_borrow
        .functions
        .iter_mut()
        .flat_map(|function| &mut function.blocks)
        .flat_map(|block| &mut block.instructions)
        .find_map(|instruction| match &mut instruction.op {
            SsaOp::Borrow {
                call: Some(metadata),
                ..
            } => Some(metadata),
            _ => None,
        })
        .unwrap();
    metadata.argument_index = 9;
    assert!(verify_ssa(bad_ssa_borrow).is_err());
}

#[test]
fn exceptional_atomic_failure_closes_borrows_and_drops_string_owners_once() {
    let directory = Directory::new();
    let parent = directory.0.display();
    let source = format!(
        "package main;import std.IO;import std.File;int main(){{string path=\"{parent}\"+\"/target\";string value=\"ne\"+\"w\";try{{std.File.writeTextAtomic(&path,&value);}}catch(std.IO.IOException error){{return 0;}}return 3;}}"
    );
    let (compilation, _) = build(&directory, &source, OptimizationLevel::O0);
    assert!(compilation.dumps[&Emit::Mir].contains("EndBorrow"));
    assert!(compilation.dumps[&Emit::Mir].contains("Drop"));
    assert!(compilation.dumps[&Emit::Ssa].contains("EndBorrow"));
    assert!(compilation.llvm.contains("invoke"));

    let injected = compilation
        .llvm
        .replace("@getrandom(", "@aether_test_getrandom(")
        .replace("declare i64 @aether_test_getrandom(ptr, i64, i32)\n", "");
    let checks = "  %atomic_allocs = load i64, ptr @aether_string_alloc_count\n  %atomic_frees = load i64, ptr @aether_string_free_count\n  %atomic_balanced = icmp eq i64 %atomic_allocs, %atomic_frees\n  %atomic_result_ok = icmp eq i32 %process_status, 0\n  %atomic_ok = and i1 %atomic_balanced, %atomic_result_ok\n  %atomic_status = select i1 %atomic_ok, i32 0, i32 99\n  ret i32 %atomic_status";
    let injected = injected.replace("  ret i32 %process_status", checks);
    let injected = format!(
        "{injected}\ndefine i64 @aether_test_getrandom(ptr %p, i64 %n, i32 %f) {{\n  %ep = call ptr @__errno_location()\n  store i32 5, ptr %ep\n  ret i64 -1\n}}\n"
    );
    assert_eq!(execute_llvm(&directory, &injected).status.code(), Some(0));
    assert!(!target_exists(&directory.0.join("target")));
    assert!(private_temps(&directory.0).is_empty());
}

fn target_exists(path: &Path) -> bool {
    fs::symlink_metadata(path).is_ok()
}
