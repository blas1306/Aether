import assert from "node:assert/strict";
import test from "node:test";
import { validateRunnableDocument } from "../src/document";

test("accepts a saved Aether file", () => {
  assert.deepEqual(
    validateRunnableDocument({
      languageId: "aether",
      isUntitled: false,
      scheme: "file",
      fsPath: "/workspace/main.ae",
    }),
    { valid: true },
  );
});

test("rejects a non-Aether document", () => {
  const result = validateRunnableDocument({
    languageId: "python",
    isUntitled: false,
    scheme: "file",
    fsPath: "/workspace/main.py",
  });
  assert.equal(result.valid, false);
  if (!result.valid) {
    assert.match(result.message, /Aether file/);
  }
});

test("rejects untitled and non-file documents", () => {
  for (const descriptor of [
    { languageId: "aether", isUntitled: true, scheme: "untitled", fsPath: "" },
    { languageId: "aether", isUntitled: false, scheme: "git", fsPath: "/workspace/main.ae" },
  ]) {
    const result = validateRunnableDocument(descriptor);
    assert.equal(result.valid, false);
    if (!result.valid) {
      assert.equal(result.message, "Save the Aether file before running it.");
    }
  }
});
