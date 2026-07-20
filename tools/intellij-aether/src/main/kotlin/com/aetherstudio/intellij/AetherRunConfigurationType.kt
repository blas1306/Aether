package com.aetherstudio.intellij

import com.intellij.execution.configurations.ConfigurationFactory
import com.intellij.execution.configurations.ConfigurationTypeBase
import com.intellij.execution.configurations.ConfigurationTypeUtil
import com.intellij.openapi.project.Project

class AetherRunConfigurationType : ConfigurationTypeBase(
    ID,
    "Aether",
    "Run an Aether script",
    AetherIcons.FILE,
) {
    val factory: ConfigurationFactory = AetherRunConfigurationFactory(this)

    init {
        addFactory(factory)
    }

    companion object {
        const val ID = "AetherRunConfiguration"

        fun getInstance(): AetherRunConfigurationType =
            ConfigurationTypeUtil.findConfigurationType(AetherRunConfigurationType::class.java)
    }
}

private class AetherRunConfigurationFactory(type: AetherRunConfigurationType) : ConfigurationFactory(type) {
    override fun getId(): String = "AetherFile"

    override fun createTemplateConfiguration(project: Project): AetherRunConfiguration =
        AetherRunConfiguration(project, this, "Aether File").apply {
            backend = AetherSettingsState.getInstance().state.backend()
        }
}
