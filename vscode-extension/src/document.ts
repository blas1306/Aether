export interface DocumentDescriptor {
  languageId: string;
  isUntitled: boolean;
  scheme: string;
  fsPath: string;
}

export type DocumentValidation =
  | { valid: true }
  | { valid: false; message: string };

export function validateRunnableDocument(document: DocumentDescriptor): DocumentValidation {
  if (document.languageId !== "aether") {
    return { valid: false, message: "Open an Aether file before running this command." };
  }
  if (document.isUntitled || document.scheme !== "file" || document.fsPath.length === 0) {
    return { valid: false, message: "Save the Aether file before running it." };
  }
  return { valid: true };
}
