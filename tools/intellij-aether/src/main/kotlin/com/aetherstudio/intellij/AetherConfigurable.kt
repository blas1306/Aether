package com.aetherstudio.intellij

import com.intellij.openapi.options.SearchableConfigurable
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.FormBuilder
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.JTextField

class AetherConfigurable : SearchableConfigurable {
    private var panel: JPanel? = null
    private var pythonPathField: JTextField? = null

    override fun getId(): String = "aether.settings"
    override fun getDisplayName(): String = "Aether"

    override fun createComponent(): JComponent {
        pythonPathField = JTextField(AetherSettingsState.getInstance().state.pythonPath)
        panel = FormBuilder.createFormBuilder()
            .addLabeledComponent(JBLabel("Python interpreter"), pythonPathField!!, 1, false)
            .addComponentFillVertically(JPanel(), 0)
            .panel
        return panel!!
    }

    override fun isModified(): Boolean =
        pythonPathField?.text.orEmpty() != AetherSettingsState.getInstance().state.pythonPath

    override fun apply() {
        AetherSettingsState.getInstance().state.pythonPath = pythonPathField?.text.orEmpty().trim()
    }

    override fun reset() {
        pythonPathField?.text = AetherSettingsState.getInstance().state.pythonPath
    }

    override fun disposeUIResources() {
        panel = null
        pythonPathField = null
    }
}
