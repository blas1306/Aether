package com.aetherstudio.intellij

import com.intellij.openapi.options.SearchableConfigurable
import com.intellij.openapi.ui.ComboBox
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.FormBuilder
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.JTextField

class AetherConfigurable : SearchableConfigurable {
    private var panel: JPanel? = null
    private var aetherExecutableField: JTextField? = null
    private var languageServerExecutableField: JTextField? = null
    private var backendField: ComboBox<AetherBackend>? = null

    override fun getId(): String = "aether.settings"
    override fun getDisplayName(): String = "Aether"

    override fun createComponent(): JComponent {
        val state = AetherSettingsState.getInstance().state
        aetherExecutableField = JTextField(state.aetherExecutable).withExecutableHint()
        languageServerExecutableField = JTextField(state.languageServerExecutable).withExecutableHint()
        backendField = ComboBox(AetherBackend.entries.toTypedArray()).apply { selectedItem = state.backend() }
        panel = FormBuilder.createFormBuilder()
            .addLabeledComponent(JBLabel("Aether executable:"), aetherExecutableField!!, 1, false)
            .addLabeledComponent(JBLabel("Aether language server executable:"), languageServerExecutableField!!, 1, false)
            .addLabeledComponent(JBLabel("Default backend:"), backendField!!, 1, false)
            .addComponent(JBLabel("Leave executable fields empty to search the project .venv and then PATH."))
            .addComponentFillVertically(JPanel(), 0)
            .panel
        return panel!!
    }

    override fun isModified(): Boolean {
        val state = AetherSettingsState.getInstance().state
        return aetherExecutableField?.text.orEmpty() != state.aetherExecutable ||
            languageServerExecutableField?.text.orEmpty() != state.languageServerExecutable ||
            (backendField?.selectedItem as? AetherBackend ?: AetherBackend.NATIVE) != state.backend()
    }

    override fun apply() {
        val state = AetherSettingsState.getInstance().state
        state.aetherExecutable = aetherExecutableField?.text.orEmpty().trim()
        state.languageServerExecutable = languageServerExecutableField?.text.orEmpty().trim()
        state.defaultBackend = (backendField?.selectedItem as? AetherBackend ?: AetherBackend.NATIVE).persistentValue
    }

    override fun reset() {
        val state = AetherSettingsState.getInstance().state
        aetherExecutableField?.text = state.aetherExecutable
        languageServerExecutableField?.text = state.languageServerExecutable
        backendField?.selectedItem = state.backend()
    }

    override fun disposeUIResources() {
        panel = null
        aetherExecutableField = null
        languageServerExecutableField = null
        backendField = null
    }

    private fun JTextField.withExecutableHint(): JTextField = apply {
        toolTipText = "Leave empty to search the project .venv and then PATH. Use a command name or a path without arguments."
    }
}
