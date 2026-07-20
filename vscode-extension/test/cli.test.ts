import assert from "node:assert/strict";
import test from "node:test";
import { buildCliArguments, formatCommand, shouldRevealOutput } from "../src/cli";

const base = {
  file: "/workspace/aether examples/hello world.ae",
  defaultBackend: "native" as const,
  optimizationLevel: "O0" as const,
};

test("native is the default run backend and paths remain one argument", () => {
  assert.deepEqual(buildCliArguments({ ...base, mode: "run" }), [base.file]);
});

test("configured and explicit AST runs use the AST backend", () => {
  assert.deepEqual(
    buildCliArguments({ ...base, mode: "run", defaultBackend: "ast" }),
    ["--backend=ast", base.file],
  );
  assert.deepEqual(buildCliArguments({ ...base, mode: "runAst" }), ["--backend=ast", base.file]);
});

test("check and emission commands use the audited CLI flags", () => {
  assert.deepEqual(buildCliArguments({ ...base, mode: "check" }), ["--check", base.file]);
  assert.deepEqual(buildCliArguments({ ...base, mode: "emitIr", optimizationLevel: "O2" }), [
    "--emit-ir",
    "-O2",
    base.file,
  ]);
  assert.deepEqual(buildCliArguments({ ...base, mode: "emitSsa" }), ["--emit-ssa", base.file]);
  assert.deepEqual(buildCliArguments({ ...base, mode: "emitLlvm" }), ["--emit-llvm", base.file]);
});

test("display formatting quotes paths but never changes the argument array", () => {
  const args = buildCliArguments({ ...base, mode: "check" });
  assert.equal(formatCommand("aether", args), `aether --check "${base.file}"`);
  assert.deepEqual(args, ["--check", base.file]);
});

test("exit codes control output reveal without reinterpreting diagnostics", () => {
  assert.equal(shouldRevealOutput("always", 0), true);
  assert.equal(shouldRevealOutput("onError", 0), false);
  assert.equal(shouldRevealOutput("onError", 1), true);
  assert.equal(shouldRevealOutput("onError", 70), true);
  assert.equal(shouldRevealOutput("onError", null), true);
  assert.equal(shouldRevealOutput("never", 3), false);
});
