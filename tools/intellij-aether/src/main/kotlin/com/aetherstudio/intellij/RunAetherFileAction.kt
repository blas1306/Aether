package com.aetherstudio.intellij

import com.intellij.execution.RunManager
import com.intellij.execution.ProgramRunnerUtil
import com.intellij.execution.executors.DefaultRunExecutor
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VirtualFile
import java.io.File

class RunAetherFileAction : AnAction() {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(event: AnActionEvent) {
        val enabled = AetherRunActionSupport.currentAetherFile(event) != null
        event.presentation.isEnabledAndVisible = enabled
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val file = AetherRunActionSupport.currentAetherFile(event) ?: return
        FileDocumentManager.getInstance().getDocument(file)?.let {
            FileDocumentManager.getInstance().saveDocument(it)
        }

        val error = AetherRunActionSupport.validationError(file)
        if (error != null) {
            Messages.showErrorDialog(project, error, "Run Aether File")
            return
        }

        val factory = AetherRunConfigurationType.getInstance().factory
        val configuration = AetherRunConfiguration(project, factory, "Run ${file.name}").apply {
            filePath = file.path
        }
        val settings = RunManager.getInstance(project).createConfiguration(configuration, factory)
        ProgramRunnerUtil.executeConfiguration(settings, DefaultRunExecutor.getRunExecutorInstance())
    }
}

internal object AetherRunActionSupport {
    fun currentAetherFile(event: AnActionEvent): VirtualFile? =
        currentAetherFile(
            explicitFile = event.getData(CommonDataKeys.VIRTUAL_FILE),
            psiFile = event.getData(CommonDataKeys.PSI_FILE)?.virtualFile,
            editorFile = event.getData(CommonDataKeys.EDITOR)?.document?.let {
                FileDocumentManager.getInstance().getFile(it)
            },
        )

    fun currentAetherFile(
        explicitFile: VirtualFile?,
        psiFile: VirtualFile?,
        editorFile: VirtualFile?,
    ): VirtualFile? {
        for (file in listOf(explicitFile, psiFile, editorFile)) {
            if (file?.extension == AetherFileType.defaultExtension) {
                return file
            }
        }
        return null
    }

    fun validationError(file: VirtualFile): String? {
        if (file.extension != AetherFileType.defaultExtension) {
            return "Run Aether File only supports .ae files."
        }
        if (!File(file.path).isFile) {
            return "Aether file does not exist: ${file.path}"
        }
        return null
    }
}
