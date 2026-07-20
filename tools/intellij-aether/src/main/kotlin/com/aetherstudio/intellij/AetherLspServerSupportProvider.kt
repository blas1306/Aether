package com.aetherstudio.intellij

import com.intellij.execution.ExecutionException
import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.execution.process.OSProcessHandler
import com.intellij.openapi.project.Project
import com.intellij.openapi.startup.StartupManager
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.LspServerSupportProvider
import com.intellij.platform.lsp.api.ProjectWideLspServerDescriptor

class AetherLspServerSupportProvider : LspServerSupportProvider {
    override fun fileOpened(project: Project, file: VirtualFile, serverStarter: LspServerSupportProvider.LspServerStarter) {
        if (file.extension == AetherFileType.defaultExtension) {
            StartupManager.getInstance(project).runAfterOpened {
                if (!project.isDisposed && file.isValid) {
                    serverStarter.ensureServerStarted(AetherLspServerDescriptor(project))
                }
            }
        }
    }
}

private class AetherLspServerDescriptor(project: Project) : ProjectWideLspServerDescriptor(project, "Aether") {
    override fun isSupportedFile(file: VirtualFile): Boolean = file.extension == AetherFileType.defaultExtension

    override fun createCommandLine(): GeneralCommandLine = AetherCommandLine.lspCommandLine(project)

    override fun startServerProcess(): OSProcessHandler = try {
        super.startServerProcess()
    } catch (error: ExecutionException) {
        throw ExecutionException(
            "Unable to start aether-lsp. Install Aether, activate or select the correct environment, " +
                "or configure the executable in Settings > Tools > Aether.",
            error,
        )
    }
}
