package com.aetherstudio.intellij

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.vfs.VirtualFile

class RunAetherFileAction : AnAction() {
    override fun update(event: AnActionEvent) {
        val enabled = event.currentAetherFile() != null
        event.presentation.isEnabledAndVisible = enabled
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val file = event.currentAetherFile() ?: return
        AetherFileRunner.run(project, file)
    }

    private fun AnActionEvent.currentAetherFile(): VirtualFile? {
        val explicitFile = getData(CommonDataKeys.VIRTUAL_FILE)
        if (explicitFile?.extension == AetherFileType.defaultExtension) {
            return explicitFile
        }

        val psiFile = getData(CommonDataKeys.PSI_FILE)?.virtualFile
        if (psiFile?.extension == AetherFileType.defaultExtension) {
            return psiFile
        }

        val editorFile = getData(CommonDataKeys.EDITOR)?.document?.let {
            FileDocumentManager.getInstance().getFile(it)
        }
        return editorFile?.takeIf { it.extension == AetherFileType.defaultExtension }
    }
}
