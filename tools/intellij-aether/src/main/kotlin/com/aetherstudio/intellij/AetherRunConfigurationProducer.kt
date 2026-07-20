package com.aetherstudio.intellij

import com.intellij.execution.actions.ConfigurationContext
import com.intellij.execution.actions.RunConfigurationProducer
import com.intellij.openapi.util.Ref
import com.intellij.openapi.vfs.VirtualFile
import com.intellij.psi.PsiElement

class AetherRunConfigurationProducer :
    RunConfigurationProducer<AetherRunConfiguration>(AetherRunConfigurationType.getInstance().factory) {

    override fun setupConfigurationFromContext(
        configuration: AetherRunConfiguration,
        context: ConfigurationContext,
        sourceElement: Ref<PsiElement>,
    ): Boolean {
        val file = context.aetherFile() ?: return false
        configuration.filePath = file.path
        configuration.backend = AetherSettingsState.getInstance().state.backend()
        configuration.name = "Run ${file.name}"
        return true
    }

    override fun isConfigurationFromContext(
        configuration: AetherRunConfiguration,
        context: ConfigurationContext,
    ): Boolean {
        val file = context.aetherFile() ?: return false
        return configuration.filePath == file.path
    }

    private fun ConfigurationContext.aetherFile(): VirtualFile? {
        val file = location?.virtualFile ?: psiLocation?.containingFile?.virtualFile ?: return null
        return file.takeIf { it.extension == AetherFileType.defaultExtension }
    }
}
