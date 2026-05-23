package com.aetherstudio.intellij

import com.intellij.icons.AllIcons
import com.intellij.openapi.components.service
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory
import com.intellij.ui.content.ContentFactory
import com.intellij.ui.components.JBScrollPane
import java.awt.BorderLayout
import javax.swing.JButton
import javax.swing.JPanel
import javax.swing.JToolBar
import javax.swing.JTextArea

class AetherToolWindowFactory : ToolWindowFactory {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val output = JTextArea().apply {
            isEditable = false
            lineWrap = false
        }
        val rerun = JButton(AllIcons.Actions.Restart).apply {
            toolTipText = "Rerun"
            isEnabled = false
        }
        val stop = JButton(AllIcons.Actions.Suspend).apply {
            toolTipText = "Stop"
            isEnabled = false
        }
        val clear = JButton(AllIcons.Actions.GC).apply {
            toolTipText = "Clear"
        }
        project.service<AetherConsoleService>().attach(project, output, rerun, stop, clear)

        val toolbar = JToolBar().apply {
            isFloatable = false
            add(rerun)
            add(stop)
            add(clear)
        }

        val panel = JPanel(BorderLayout()).apply {
            add(toolbar, BorderLayout.NORTH)
            add(JBScrollPane(output), BorderLayout.CENTER)
        }
        val content = ContentFactory.getInstance().createContent(panel, "Output", false)
        toolWindow.contentManager.addContent(content)
    }
}
