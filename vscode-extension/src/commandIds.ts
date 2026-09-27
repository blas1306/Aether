export const COMMAND_IDS = [
  "aether.run",
  "aether.check",
  "aether.emitAst",
  "aether.emitHir",
  "aether.emitMir",
  "aether.emitSsa",
  "aether.emitLlvm",
  "aether.restartLanguageServer",
  "aether.showOutput",
] as const;

export type AetherCommandId = (typeof COMMAND_IDS)[number];
