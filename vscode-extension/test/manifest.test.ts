import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { COMMAND_IDS } from "../src/commandIds";

const extensionRoot = path.resolve(__dirname, "../..");

function readJson(relativePath: string): unknown {
  return JSON.parse(readFileSync(path.join(extensionRoot, relativePath), "utf8")) as unknown;
}

test("TextMate grammar is valid JSON with the expected scope", () => {
  const grammar = readJson("syntaxes/aether.tmLanguage.json") as {
    scopeName?: string;
    repository?: Record<string, unknown>;
  };
  assert.equal(grammar.scopeName, "source.aether");
  assert.ok(grammar.repository?.keywords);
  assert.ok(grammar.repository?.strings);
  assert.ok(grammar.repository?.comments);
});

test("manifest consistently registers Aether, commands, and defaults", () => {
  const manifest = readJson("package.json") as {
    activationEvents: string[];
    contributes: {
      languages: Array<{ id: string; extensions: string[] }>;
      commands: Array<{ command: string }>;
      configuration: { properties: Record<string, { default: unknown }> };
    };
  };
  const language = manifest.contributes.languages.find(({ id }) => id === "aether");
  assert.ok(language);
  assert.deepEqual(language.extensions, [".ae"]);
  assert.equal(manifest.contributes.configuration.properties["aether.defaultBackend"]?.default, "native");
  assert.deepEqual(
    manifest.contributes.commands.map(({ command }) => command),
    [...COMMAND_IDS],
  );
  for (const command of COMMAND_IDS) {
    assert.ok(manifest.activationEvents.includes(`onCommand:${command}`));
  }
  assert.ok(manifest.activationEvents.includes("onLanguage:aether"));
});

test("language configuration includes required comment and pairing support", () => {
  const configuration = readJson("language-configuration.json") as {
    comments: { lineComment: string; blockComment: string[] };
    brackets: string[][];
  };
  assert.equal(configuration.comments.lineComment, "//");
  assert.deepEqual(configuration.comments.blockComment, ["/*", "*/"]);
  assert.deepEqual(configuration.brackets, [
    ["{", "}"],
    ["[", "]"],
    ["(", ")"],
  ]);
});
