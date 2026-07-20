import * as path from "node:path";
import * as vscode from "vscode";
import { COMMAND_IDS } from "./commandIds";
import type { AetherMode } from "./cli";
import { readAetherConfiguration } from "./configuration";
import { validateRunnableDocument } from "./document";
import type { AetherLanguageClient } from "./lsp";
import type { AetherOutput } from "./output";
import type { AetherRunner } from "./runner";

export function registerAetherCommands(
  runner: AetherRunner,
  languageClient: AetherLanguageClient,
  output: AetherOutput,
): vscode.Disposable[] {
  const modes = new Map<string, AetherMode>([
    ["aether.run", "run"],
    ["aether.check", "check"],
    ["aether.runAst", "runAst"],
    ["aether.emitIr", "emitIr"],
    ["aether.emitSsa", "emitSsa"],
    ["aether.emitLlvm", "emitLlvm"],
  ]);

  return COMMAND_IDS.map((commandId) => {
    if (commandId === "aether.restartLanguageServer") {
      return vscode.commands.registerCommand(commandId, async () => languageClient.restart());
    }
    if (commandId === "aether.showOutput") {
      return vscode.commands.registerCommand(commandId, () => output.show());
    }
    const mode = modes.get(commandId);
    if (mode === undefined) {
      throw new Error(`No handler configured for ${commandId}`);
    }
    return vscode.commands.registerCommand(commandId, async () => runForActiveEditor(mode, runner));
  });
}

async function runForActiveEditor(mode: AetherMode, runner: AetherRunner): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (editor === undefined) {
    void vscode.window.showWarningMessage("Open an Aether file before running this command.");
    return;
  }

  const document = editor.document;
  const initialValidation = validateRunnableDocument({
    languageId: document.languageId,
    isUntitled: document.isUntitled,
    scheme: document.uri.scheme,
    fsPath: document.uri.fsPath,
  });
  if (!initialValidation.valid) {
    void vscode.window.showWarningMessage(initialValidation.message);
    return;
  }

  if (document.isDirty && !(await document.save())) {
    void vscode.window.showWarningMessage("Save the Aether file before running it.");
    return;
  }

  const workspaceFolder = vscode.workspace.getWorkspaceFolder(document.uri);
  const cwd = workspaceFolder?.uri.fsPath ?? path.dirname(document.uri.fsPath);
  const configuration = readAetherConfiguration(vscode.workspace.getConfiguration("aether", document.uri));
  await runner.runAetherCommand({
    file: document.uri.fsPath,
    cwd,
    mode,
    configuration,
  });
}
