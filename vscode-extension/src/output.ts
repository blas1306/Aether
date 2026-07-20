import * as vscode from "vscode";

export class AetherOutput implements vscode.Disposable {
  readonly channel: vscode.OutputChannel;

  constructor() {
    this.channel = vscode.window.createOutputChannel("Aether");
  }

  appendLine(value: string): void {
    this.channel.appendLine(value);
  }

  show(): void {
    this.channel.show(true);
  }

  dispose(): void {
    this.channel.dispose();
  }
}
