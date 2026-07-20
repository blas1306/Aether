import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import * as vscode from "vscode";
import { buildCliArguments, formatCommand, shouldRevealOutput, type AetherMode } from "./cli";
import type { AetherConfiguration } from "./configuration";
import type { AetherOutput } from "./output";

export interface RunAetherCommandOptions {
  file: string;
  cwd: string;
  mode: AetherMode;
  configuration: AetherConfiguration;
}

export interface ProcessResult {
  exitCode: number | null;
  signal: NodeJS.Signals | null;
}

export class AetherRunner implements vscode.Disposable {
  private readonly processes = new Set<ChildProcessWithoutNullStreams>();

  constructor(private readonly output: AetherOutput) {}

  runAetherCommand(options: RunAetherCommandOptions): Promise<ProcessResult> {
    const args = buildCliArguments({
      mode: options.mode,
      file: options.file,
      defaultBackend: options.configuration.defaultBackend,
      optimizationLevel: options.configuration.optimizationLevel,
    });

    this.output.appendLine("");
    this.output.appendLine(`> ${formatCommand(options.configuration.executable, args)}`);

    return new Promise((resolve) => {
      let settled = false;
      const child = spawn(options.configuration.executable, args, {
        cwd: options.cwd,
        shell: false,
        windowsHide: true,
      });
      this.processes.add(child);

      child.stdout.on("data", (chunk: Buffer) => this.output.channel.append(chunk.toString("utf8")));
      child.stderr.on("data", (chunk: Buffer) => this.output.channel.append(chunk.toString("utf8")));

      child.on("error", (error: Error) => {
        this.processes.delete(child);
        this.output.appendLine(`Failed to start Aether: ${error.message}`);
        if (options.configuration.revealOutput !== "never") {
          this.output.show();
        }
        void vscode.window.showErrorMessage(
          "Could not start Aether. Check that it is installed and available in PATH.",
        );
        if (!settled) {
          settled = true;
          resolve({ exitCode: null, signal: null });
        }
      });

      child.on("close", (exitCode: number | null, signal: NodeJS.Signals | null) => {
        this.processes.delete(child);
        this.output.appendLine(`[exit code: ${exitCode === null ? "none" : exitCode}${signal ? `, signal: ${signal}` : ""}]`);
        if (shouldRevealOutput(options.configuration.revealOutput, exitCode)) {
          this.output.show();
        }
        if (!settled) {
          settled = true;
          resolve({ exitCode, signal });
        }
      });
    });
  }

  dispose(): void {
    for (const process of this.processes) {
      process.kill();
    }
    this.processes.clear();
  }
}
