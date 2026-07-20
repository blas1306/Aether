package com.aetherstudio.intellij

import com.intellij.execution.ProgramRunnerUtil
import com.intellij.execution.RunManager
import com.intellij.execution.executors.DefaultRunExecutor
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.LspServerManager
import java.io.File

open class AetherFileCommandAction(private val mode: AetherCommandMode) : AnAction() {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(event: AnActionEvent) {
        event.presentation.isEnabledAndVisible = AetherRunActionSupport.currentAetherFile(event) != null
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val file = AetherRunActionSupport.currentAetherFile(event) ?: return
        FileDocumentManager.getInstance().getDocument(file)?.let(FileDocumentManager.getInstance()::saveDocument)

        AetherRunActionSupport.validationError(file)?.let { error ->
            Messages.showErrorDialog(project, error, actionTitle(mode))
            return
        }

        val factory = AetherRunConfigurationType.getInstance().factory
        val configuration = AetherRunConfiguration(project, factory, configurationName(mode, file.name)).apply {
            filePath = file.path
            backend = when (mode) {
                AetherCommandMode.RUN_AST -> AetherBackend.AST
                else -> AetherBackend.NATIVE
            }
            commandMode = mode
        }
        val settings = RunManager.getInstance(project).createConfiguration(configuration, factory)
        ProgramRunnerUtil.executeConfiguration(settings, DefaultRunExecutor.getRunExecutorInstance())
    }

    private fun actionTitle(mode: AetherCommandMode): String = when (mode) {
        AetherCommandMode.RUN_NATIVE -> "Run Aether File"
        AetherCommandMode.RUN_AST -> "Run Aether File with AST Backend"
        AetherCommandMode.CHECK -> "Check Aether File"
        AetherCommandMode.EMIT_IR -> "Emit Aether IR"
        AetherCommandMode.EMIT_SSA -> "Emit Aether SSA"
        AetherCommandMode.EMIT_LLVM -> "Emit Aether LLVM"
    }

    private fun configurationName(mode: AetherCommandMode, fileName: String): String =
        "${actionTitle(mode)}: $fileName"
}

class RunAetherFileAction : AetherFileCommandAction(AetherCommandMode.RUN_NATIVE)
class RunAetherFileAstAction : AetherFileCommandAction(AetherCommandMode.RUN_AST)
class CheckAetherFileAction : AetherFileCommandAction(AetherCommandMode.CHECK)
class EmitAetherIrAction : AetherFileCommandAction(AetherCommandMode.EMIT_IR)
class EmitAetherSsaAction : AetherFileCommandAction(AetherCommandMode.EMIT_SSA)
class EmitAetherLlvmAction : AetherFileCommandAction(AetherCommandMode.EMIT_LLVM)

class RestartAetherLanguageServerAction : AnAction() {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(event: AnActionEvent) {
        event.presentation.isEnabledAndVisible = event.project != null
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        LspServerManager.getInstance(project).stopAndRestartIfNeeded(AetherLspServerSupportProvider::class.java)
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
            if (file?.extension.equals(AetherFileType.defaultExtension, ignoreCase = true)) {
                return file
            }
        }
        return null
    }

    fun validationError(file: VirtualFile): String? {
        if (!file.extension.equals(AetherFileType.defaultExtension, ignoreCase = true)) {
            return "This action only supports .ae files."
        }
        if (!File(file.path).isFile) {
            return "Aether file does not exist: ${file.path}"
        }
        return null
    }
}
