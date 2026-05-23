package com.aetherstudio.intellij

import com.intellij.execution.process.OSProcessHandler
import com.intellij.execution.process.ProcessEvent
import com.intellij.execution.process.ProcessListener
import com.intellij.openapi.components.service
import com.intellij.openapi.fileEditor.FileDocumentManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.util.Key
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.openapi.wm.ToolWindowManager

object AetherFileRunner {
    fun run(project: Project, file: VirtualFile) {
        if (file.extension != AetherFileType.defaultExtension) {
            return
        }

        FileDocumentManager.getInstance().getDocument(file)?.let {
            FileDocumentManager.getInstance().saveDocument(it)
        }

        val console = project.service<AetherConsoleService>()
        ToolWindowManager.getInstance(project).getToolWindow("Aether")?.show()
        console.setLastFile(file)
        console.clear()
        console.append("$ ${AetherCommandLine.pythonExecutable(project.basePath, AetherSettingsState.getInstance().state.pythonPath)} -m aether_lsp.run_file ${file.path}\n\n")

        val handler = OSProcessHandler(AetherCommandLine.runFileCommandLine(project, file.path))
        console.setProcessHandler(handler)
        handler.addProcessListener(
            object : ProcessListener {
                override fun onTextAvailable(event: ProcessEvent, outputType: Key<*>) {
                    console.append(event.text)
                }

                override fun processTerminated(event: ProcessEvent) {
                    if (event.exitCode != 0) {
                        console.append("\nProcess exited with code ${event.exitCode}\n")
                    }
                    console.clearProcessHandler(handler)
                }
            }
        )
        handler.startNotify()
    }
}
