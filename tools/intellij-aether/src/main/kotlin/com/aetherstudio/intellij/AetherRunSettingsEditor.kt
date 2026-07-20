package com.aetherstudio.intellij

import com.intellij.openapi.fileChooser.FileChooserDescriptorFactory
import com.intellij.openapi.options.SettingsEditor
import com.intellij.openapi.ui.ComboBox
import com.intellij.openapi.ui.TextFieldWithBrowseButton
import com.intellij.ui.components.JBLabel
import com.intellij.util.ui.FormBuilder
import javax.swing.JComponent
import javax.swing.JPanel

class AetherRunSettingsEditor : SettingsEditor<AetherRunConfiguration>() {
    private val fileField = TextFieldWithBrowseButton()
    private val backendField = ComboBox(AetherBackend.entries.toTypedArray())
    private val panel: JPanel

    init {
        val descriptor = FileChooserDescriptorFactory.createSingleFileDescriptor(AetherFileType.defaultExtension)
            .withTitle("Choose Aether File")
        fileField.addBrowseFolderListener(null, descriptor)
        panel = FormBuilder.createFormBuilder()
            .addLabeledComponent(JBLabel("Aether file:"), fileField, 1, false)
            .addLabeledComponent(JBLabel("Backend:"), backendField, 1, false)
            .addComponentFillVertically(JPanel(), 0)
            .panel
    }

    override fun resetEditorFrom(configuration: AetherRunConfiguration) {
        fileField.text = configuration.filePath
        backendField.selectedItem = configuration.backend
    }

    override fun applyEditorTo(configuration: AetherRunConfiguration) {
        configuration.filePath = fileField.text.trim()
        configuration.backend = backendField.selectedItem as? AetherBackend ?: AetherBackend.NATIVE
        configuration.commandMode = when (configuration.backend) {
            AetherBackend.NATIVE -> AetherCommandMode.RUN_NATIVE
            AetherBackend.AST -> AetherCommandMode.RUN_AST
        }
    }

    override fun createEditor(): JComponent = panel
}
