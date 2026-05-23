package com.aetherstudio.intellij

import com.intellij.execution.configurations.GeneralCommandLine
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.platform.lsp.api.LspServerSupportProvider
import com.intellij.platform.lsp.api.ProjectWideLspServerDescriptor

class AetherLspServerSupportProvider : LspServerSupportProvider {
    override fun fileOpened(project: Project, file: VirtualFile, serverStarter: LspServerSupportProvider.LspServerStarter) {
        if (file.extension == AetherFileType.defaultExtension) {
            serverStarter.ensureServerStarted(AetherLspServerDescriptor(project))
        }
    }
}

private class AetherLspServerDescriptor(project: Project) : ProjectWideLspServerDescriptor(project, "Aether") {
    override fun isSupportedFile(file: VirtualFile): Boolean = file.extension == AetherFileType.defaultExtension

    override fun createCommandLine(): GeneralCommandLine = AetherCommandLine.lspCommandLine(project)
}
