package com.aetherstudio.intellij

import com.intellij.codeInsight.editorActions.TypedHandlerDelegate
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.fileTypes.FileType
import com.intellij.openapi.project.Project
import com.intellij.psi.PsiFile

class AetherTypedHandler : TypedHandlerDelegate() {
    override fun beforeCharTyped(
        c: Char,
        project: Project,
        editor: Editor,
        file: PsiFile,
        fileType: FileType,
    ): Result {
        if (file !is AetherPsiFile || editor.selectionModel.hasSelection()) {
            return Result.CONTINUE
        }

        val closing = AetherTypingSupport.matchingClosing(c)
        if (closing != null) {
            return insertPair(editor, c, closing)
        }

        if (c in AetherTypingSupport.closingBraces) {
            return skipExistingClosingBrace(editor, c)
        }

        return Result.CONTINUE
    }

    private fun insertPair(editor: Editor, opening: Char, closing: Char): Result {
        val caret = editor.caretModel.currentCaret
        val offset = caret.offset
        if (offset > editor.document.textLength) {
            return Result.CONTINUE
        }

        editor.document.insertString(offset, "$opening$closing")
        caret.moveToOffset(offset + 1)
        return Result.STOP
    }

    private fun skipExistingClosingBrace(editor: Editor, closing: Char): Result {
        val caret = editor.caretModel.currentCaret
        val offset = caret.offset
        val chars = editor.document.charsSequence
        if (offset >= chars.length || chars[offset] != closing) {
            return Result.CONTINUE
        }

        caret.moveToOffset(offset + 1)
        return Result.STOP
    }
}
