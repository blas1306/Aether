package com.aetherstudio.intellij

import com.intellij.execution.lineMarker.RunLineMarkerContributor
import com.intellij.icons.AllIcons
import com.intellij.openapi.actionSystem.ActionManager
import com.intellij.psi.PsiElement

class AetherRunLineMarkerContributor : RunLineMarkerContributor() {
    override fun getInfo(element: PsiElement): Info? {
        val file = element.containingFile as? AetherPsiFile ?: return null
        val virtualFile = file.virtualFile ?: return null
        if (virtualFile.extension != AetherFileType.defaultExtension) {
            return null
        }
        if (element.textRange.startOffset != firstRunnableOffset(file.text)) {
            return null
        }

        val action = ActionManager.getInstance().getAction("Aether.RunFile") ?: return null
        return Info(AllIcons.Actions.Execute, arrayOf(action)) { "Run ${virtualFile.name}" }
    }

    private fun firstRunnableOffset(text: String): Int {
        val index = text.indexOfFirst { !it.isWhitespace() }
        return if (index >= 0) index else 0
    }
}
