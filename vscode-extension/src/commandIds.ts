export const COMMAND_IDS = [
  "aether.run",
  "aether.check",
  "aether.runAst",
  "aether.emitIr",
  "aether.emitSsa",
  "aether.emitLlvm",
  "aether.restartLanguageServer",
  "aether.showOutput",
] as const;

export type AetherCommandId = (typeof COMMAND_IDS)[number];
