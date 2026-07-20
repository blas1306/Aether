import * as vscode from "vscode";
import { registerAetherCommands } from "./commands";
import { AetherLanguageClient } from "./lsp";
import { AetherOutput } from "./output";
import { AetherRunner } from "./runner";

let languageClient: AetherLanguageClient | undefined;

export function activate(context: vscode.ExtensionContext): void {
  const output = new AetherOutput();
  const runner = new AetherRunner(output);
  const fileWatcher = vscode.workspace.createFileSystemWatcher("**/*.ae");
  languageClient = new AetherLanguageClient(output, fileWatcher);

  context.subscriptions.push(
    output,
    runner,
    fileWatcher,
    languageClient,
    ...registerAetherCommands(runner, languageClient, output),
  );

  void languageClient.start();
}

export async function deactivate(): Promise<void> {
  await languageClient?.stop();
  languageClient = undefined;
}
