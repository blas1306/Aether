import type { WorkspaceConfiguration } from "vscode";

export type AetherBackend = "native" | "ast";
export type OptimizationLevel = "O0" | "O1" | "O2";
export type RevealOutput = "always" | "onError" | "never";

export interface AetherConfiguration {
  executable: string;
  lspExecutable: string;
  defaultBackend: AetherBackend;
  optimizationLevel: OptimizationLevel;
  revealOutput: RevealOutput;
}

const BACKENDS = new Set<AetherBackend>(["native", "ast"]);
const OPTIMIZATION_LEVELS = new Set<OptimizationLevel>(["O0", "O1", "O2"]);
const REVEAL_OUTPUT_VALUES = new Set<RevealOutput>(["always", "onError", "never"]);

function stringSetting(configuration: WorkspaceConfiguration, key: string, fallback: string): string {
  const value = configuration.get<unknown>(key);
  return typeof value === "string" && value.trim().length > 0 ? value.trim() : fallback;
}

function enumSetting<T extends string>(
  configuration: WorkspaceConfiguration,
  key: string,
  values: ReadonlySet<T>,
  fallback: T,
): T {
  const value = configuration.get<unknown>(key);
  return typeof value === "string" && values.has(value as T) ? (value as T) : fallback;
}

export function readAetherConfiguration(configuration: WorkspaceConfiguration): AetherConfiguration {
  return {
    executable: stringSetting(configuration, "executable", "aether"),
    lspExecutable: stringSetting(configuration, "lsp.executable", "aether-lsp"),
    defaultBackend: enumSetting(configuration, "defaultBackend", BACKENDS, "native"),
    optimizationLevel: enumSetting(configuration, "optimizationLevel", OPTIMIZATION_LEVELS, "O0"),
    revealOutput: enumSetting(configuration, "revealOutput", REVEAL_OUTPUT_VALUES, "onError"),
  };
}
