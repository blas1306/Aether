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
    repository?: Record<string, { match?: string }>;
  };
  assert.equal(grammar.scopeName, "source.aether");
  assert.ok(grammar.repository?.keywords);
  assert.ok(grammar.repository?.strings);
  assert.ok(grammar.repository?.comments);
  assert.match(grammar.repository?.types?.match ?? "", /\bError\b/);
  assert.doesNotMatch(grammar.repository?.types?.match ?? "", /\bException\b/);
  assert.match(JSON.stringify(grammar.repository?.keywords), /try\|catch\|throw/);
});

test("function declarations scope both their return type and function name", () => {
  const grammar = readJson("syntaxes/aether.tmLanguage.json") as {
    repository?: {
      functionDeclarations?: {
        patterns?: Array<{
          match?: string;
          captures?: Record<string, { name?: string }>;
        }>;
      };
    };
  };
  const declaration = grammar.repository?.functionDeclarations?.patterns?.[0];
  assert.ok(declaration?.match);
  assert.equal(declaration.captures?.["1"]?.name, "storage.type.aether");
  assert.equal(declaration.captures?.["2"]?.name, "entity.name.function.aether");

  const match = new RegExp(declaration.match).exec("double hola(double x) {");
  assert.equal(match?.[1], "double");
  assert.equal(match?.[2], "hola");
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
