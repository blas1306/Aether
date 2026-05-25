package com.aetherstudio.intellij

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.ActionUpdateThread
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.command.WriteCommandAction
import com.intellij.openapi.fileEditor.FileEditorManager
import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.ui.Messages
import com.intellij.openapi.vfs.VfsUtil
import com.intellij.openapi.vfs.VirtualFile

internal object AetherNewFileSupport {
    const val DEFAULT_CONTENT: String = "println(\"Hello, Aether\");\n"

    fun normalizeFileName(input: String?): String? {
        val trimmed = input?.trim().orEmpty()
        if (trimmed.isEmpty()) {
            return null
        }
        return if (trimmed.endsWith(".${AetherFileType.defaultExtension}")) {
            trimmed
        } else {
            "$trimmed.${AetherFileType.defaultExtension}"
        }
    }

    fun isValidFileName(fileName: String): Boolean =
        fileName.isNotBlank() && '/' !in fileName && '\\' !in fileName

    fun targetDirectory(selectedFile: VirtualFile?): VirtualFile? =
        when {
            selectedFile == null -> null
            selectedFile.isDirectory -> selectedFile
            else -> selectedFile.parent
        }
}

class NewAetherFileAction : AnAction(), DumbAware {
    override fun getActionUpdateThread(): ActionUpdateThread = ActionUpdateThread.BGT

    override fun update(event: AnActionEvent) {
        val enabled = event.project != null && AetherNewFileSupport.targetDirectory(
            event.getData(CommonDataKeys.VIRTUAL_FILE),
        ) != null
        event.presentation.isEnabledAndVisible = enabled
    }

    override fun actionPerformed(event: AnActionEvent) {
        val project = event.project ?: return
        val targetDirectory = AetherNewFileSupport.targetDirectory(event.getData(CommonDataKeys.VIRTUAL_FILE)) ?: return
        val rawName = Messages.showInputDialog(
            project,
            "Enter Aether file name:",
            "New Aether File",
            AetherIcons.FILE,
        ) ?: return
        val fileName = AetherNewFileSupport.normalizeFileName(rawName)
        if (fileName == null || !AetherNewFileSupport.isValidFileName(fileName)) {
            Messages.showErrorDialog(project, "Enter a valid Aether file name.", "New Aether File")
            return
        }
        if (targetDirectory.findChild(fileName) != null) {
            Messages.showErrorDialog(project, "A file named '$fileName' already exists.", "New Aether File")
            return
        }

        try {
            val createdFile = createFile(project, targetDirectory, fileName)
            FileEditorManager.getInstance(project).openFile(createdFile, true)
        } catch (exception: Exception) {
            Messages.showErrorDialog(
                project,
                "Could not create '$fileName': ${exception.message ?: exception.javaClass.simpleName}",
                "New Aether File",
            )
        }
    }

    private fun createFile(project: com.intellij.openapi.project.Project, targetDirectory: VirtualFile, fileName: String): VirtualFile {
        var createdFile: VirtualFile? = null
        WriteCommandAction.runWriteCommandAction(project, "Create Aether File", null, Runnable {
            createdFile = targetDirectory.createChildData(this, fileName)
            VfsUtil.saveText(createdFile!!, AetherNewFileSupport.DEFAULT_CONTENT)
        })
        return createdFile ?: error("Aether file was not created.")
    }
}
