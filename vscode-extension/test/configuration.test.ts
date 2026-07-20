import assert from "node:assert/strict";
import test from "node:test";
import type { WorkspaceConfiguration } from "vscode";
import { readAetherConfiguration } from "../src/configuration";

function configuration(values: Record<string, unknown>): WorkspaceConfiguration {
  return {
    get<T>(key: string): T | undefined {
      return values[key] as T | undefined;
    },
  } as WorkspaceConfiguration;
}

test("configuration defaults to external executables and native", () => {
  assert.deepEqual(readAetherConfiguration(configuration({})), {
    executable: "aether",
    lspExecutable: "aether-lsp",
    defaultBackend: "native",
    optimizationLevel: "O0",
    revealOutput: "onError",
  });
});

test("configuration reads supported values and trims executable paths", () => {
  assert.deepEqual(
    readAetherConfiguration(
      configuration({
        executable: "  C:\\Program Files\\Aether\\aether.exe  ",
        "lsp.executable": "custom-lsp",
        defaultBackend: "ast",
        optimizationLevel: "O2",
        revealOutput: "always",
      }),
    ),
    {
      executable: "C:\\Program Files\\Aether\\aether.exe",
      lspExecutable: "custom-lsp",
      defaultBackend: "ast",
      optimizationLevel: "O2",
      revealOutput: "always",
    },
  );
});

test("invalid public configuration values fall back safely", () => {
  const result = readAetherConfiguration(
    configuration({ defaultBackend: "llvm", optimizationLevel: "O9", revealOutput: "sometimes" }),
  );
  assert.equal(result.defaultBackend, "native");
  assert.equal(result.optimizationLevel, "O0");
  assert.equal(result.revealOutput, "onError");
});
