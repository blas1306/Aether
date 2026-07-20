import * as vscode from "vscode";
import {
  LanguageClient,
  type LanguageClientOptions,
  type ServerOptions,
} from "vscode-languageclient/node";
import { readAetherConfiguration } from "./configuration";
import type { AetherOutput } from "./output";

export class AetherLanguageClient implements vscode.Disposable {
  private client: LanguageClient | undefined;
  private starting: Promise<void> | undefined;

  constructor(
    private readonly output: AetherOutput,
    private readonly fileWatcher: vscode.FileSystemWatcher,
  ) {}

  async start(): Promise<void> {
    if (this.client !== undefined) {
      return;
    }
    if (this.starting !== undefined) {
      return this.starting;
    }

    this.starting = this.startClient().catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      this.output.appendLine(`Failed to start Aether language server: ${message}`);
      this.output.show();
      void vscode.window.showErrorMessage(
        "Could not start aether-lsp. Check that Aether is installed and available in PATH.",
      );
    });
    try {
      await this.starting;
    } finally {
      this.starting = undefined;
    }
  }

  async restart(): Promise<void> {
    this.output.appendLine("Restarting Aether language server...");
    await this.stop();
    await this.start();
  }

  async stop(): Promise<void> {
    const client = this.client;
    this.client = undefined;
    if (client !== undefined) {
      try {
        await client.stop();
      } catch (error: unknown) {
        const message = error instanceof Error ? error.message : String(error);
        this.output.appendLine(`Failed to stop Aether language server cleanly: ${message}`);
      }
    }
  }

  dispose(): void {
    void this.stop().catch((error: unknown) => {
      const message = error instanceof Error ? error.message : String(error);
      this.output.appendLine(`Unexpected language server shutdown error: ${message}`);
    });
  }

  private async startClient(): Promise<void> {
    const configuration = readAetherConfiguration(vscode.workspace.getConfiguration("aether"));
    const serverOptions: ServerOptions = {
      command: configuration.lspExecutable,
      args: ["--stdio"],
    };
    const clientOptions: LanguageClientOptions = {
      documentSelector: [
        { scheme: "file", language: "aether" },
        { scheme: "untitled", language: "aether" },
      ],
      synchronize: {
        fileEvents: this.fileWatcher,
      },
      outputChannel: this.output.channel,
    };

    const client = new LanguageClient(
      "aetherLanguageServer",
      "Aether Language Server",
      serverOptions,
      clientOptions,
    );
    this.client = client;
    this.output.appendLine(`Starting language server: ${configuration.lspExecutable} --stdio`);
    try {
      await client.start();
    } catch (error: unknown) {
      if (this.client === client) {
        this.client = undefined;
      }
      throw error;
    }
  }
}
