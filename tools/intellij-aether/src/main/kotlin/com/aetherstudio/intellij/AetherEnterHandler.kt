package com.aetherstudio.intellij

import com.intellij.codeInsight.editorActions.enter.EnterHandlerDelegate
import com.intellij.codeInsight.editorActions.enter.EnterHandlerDelegateAdapter
import com.intellij.openapi.actionSystem.DataContext
import com.intellij.openapi.editor.Editor
import com.intellij.openapi.editor.actionSystem.EditorActionHandler
import com.intellij.openapi.util.Ref
import com.intellij.psi.PsiFile

class AetherEnterHandler : EnterHandlerDelegateAdapter() {
    override fun preprocessEnter(
        file: PsiFile,
        editor: Editor,
        caretOffsetRef: Ref<Int>,
        caretAdvanceRef: Ref<Int>,
        dataContext: DataContext,
        originalHandler: EditorActionHandler?,
    ): EnterHandlerDelegate.Result {
        if (file !is AetherPsiFile) {
            return EnterHandlerDelegate.Result.Continue
        }

        val offset = caretOffsetRef.get()
        val insertion = AetherTypingSupport.enterBetweenBracesInsertion(
            editor.document.charsSequence,
            offset,
            AetherTypingSupport.indentUnit,
        ) ?: return EnterHandlerDelegate.Result.Continue

        editor.document.insertString(offset, insertion.text)
        editor.caretModel.moveToOffset(offset + insertion.caretShift)
        return EnterHandlerDelegate.Result.Stop
    }
}
