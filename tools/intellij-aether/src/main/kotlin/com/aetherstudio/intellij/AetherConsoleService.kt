package com.aetherstudio.intellij

import com.intellij.execution.process.ProcessHandler
import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.project.Project
import com.intellij.openapi.vfs.VirtualFile
import javax.swing.JButton
import javax.swing.JTextArea

class AetherConsoleService {
    private var outputArea: JTextArea? = null
    private var rerunButton: JButton? = null
    private var stopButton: JButton? = null
    private var lastFile: VirtualFile? = null
    private var processHandler: ProcessHandler? = null

    fun attach(project: Project, area: JTextArea, rerun: JButton, stop: JButton, clear: JButton) {
        outputArea = area
        rerunButton = rerun
        stopButton = stop

        rerun.addActionListener {
            lastFile?.let { AetherFileRunner.run(project, it) }
        }
        stop.addActionListener {
            processHandler?.destroyProcess()
        }
        clear.addActionListener {
            clear()
        }
        updateControls()
    }

    fun clear() {
        ApplicationManager.getApplication().invokeLater {
            outputArea?.text = ""
        }
    }

    fun append(text: String) {
        ApplicationManager.getApplication().invokeLater {
            val area = outputArea ?: return@invokeLater
            area.append(text)
            area.caretPosition = area.document.length
        }
    }

    fun setLastFile(file: VirtualFile) {
        lastFile = file
        updateControls()
    }

    fun setProcessHandler(handler: ProcessHandler) {
        processHandler = handler
        updateControls()
    }

    fun clearProcessHandler(handler: ProcessHandler) {
        if (processHandler === handler) {
            processHandler = null
            updateControls()
        }
    }

    private fun updateControls() {
        ApplicationManager.getApplication().invokeLater {
            rerunButton?.isEnabled = lastFile != null
            stopButton?.isEnabled = processHandler != null && !processHandler!!.isProcessTerminated
        }
    }
}
