import type { AetherBackend, OptimizationLevel, RevealOutput } from "./configuration";

export type AetherMode = "run" | "check" | "runAst" | "emitIr" | "emitSsa" | "emitLlvm";

export interface CliArgumentsOptions {
  mode: AetherMode;
  file: string;
  defaultBackend: AetherBackend;
  optimizationLevel: OptimizationLevel;
}

export function buildCliArguments(options: CliArgumentsOptions): string[] {
  const { mode, file } = options;
  switch (mode) {
    case "run":
      return options.defaultBackend === "ast" ? ["--backend=ast", file] : [file];
    case "check":
      return ["--check", file];
    case "runAst":
      return ["--backend=ast", file];
    case "emitIr":
      return ["--emit-ir", `-${options.optimizationLevel}`, file];
    case "emitSsa":
      return ["--emit-ssa", file];
    case "emitLlvm":
      return ["--emit-llvm", file];
  }
}

export function shouldRevealOutput(setting: RevealOutput, exitCode: number | null): boolean {
  return setting === "always" || (setting === "onError" && exitCode !== 0);
}

export function formatCommand(executable: string, args: readonly string[]): string {
  return [executable, ...args].map(quoteForDisplay).join(" ");
}

function quoteForDisplay(argument: string): string {
  if (argument.length > 0 && !/[\s"\\]/u.test(argument)) {
    return argument;
  }
  return `"${argument.replace(/(["\\])/gu, "\\$1")}"`;
}
