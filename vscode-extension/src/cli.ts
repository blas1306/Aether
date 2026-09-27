import type { OptimizationLevel, RevealOutput } from "./configuration";

export type AetherMode = "run" | "check" | "emitAst" | "emitHir" | "emitMir" | "emitSsa" | "emitLlvm";

export interface CliArgumentsOptions {
  mode: AetherMode;
  file: string;
  optimizationLevel: OptimizationLevel;
}

export function buildCliArguments(options: CliArgumentsOptions): string[] {
  const { mode, file } = options;
  switch (mode) {
    case "run":
      return ["run", file, `-${options.optimizationLevel}`];
    case "check":
      return ["check", file, `-${options.optimizationLevel}`];
    case "emitAst":
      return ["check", file, "--emit", "ast", `-${options.optimizationLevel}`];
    case "emitHir":
      return ["check", file, "--emit", "hir", `-${options.optimizationLevel}`];
    case "emitMir":
      return ["check", file, "--emit", "mir", `-${options.optimizationLevel}`];
    case "emitSsa":
      return ["check", file, "--emit", "ssa", `-${options.optimizationLevel}`];
    case "emitLlvm":
      return ["build", file, "--emit", "llvm", `-${options.optimizationLevel}`];
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
