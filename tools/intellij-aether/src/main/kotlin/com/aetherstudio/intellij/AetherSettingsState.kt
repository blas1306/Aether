package com.aetherstudio.intellij

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

@State(name = "AetherSettings", storages = [Storage("aether.xml")])
class AetherSettingsState : PersistentStateComponent<AetherSettingsState.State> {
    data class State(
        var aetherExecutable: String = "",
        var languageServerExecutable: String = "",
        var defaultBackend: String = AetherBackend.NATIVE.persistentValue,
        // Retained only so older aether.xml files continue to deserialize safely.
        @Deprecated("Aether executables no longer use a Python interpreter")
        var pythonPath: String = "",
    ) {
        fun backend(): AetherBackend = AetherBackend.fromPersistentValue(defaultBackend)
    }

    private var state = State()

    override fun getState(): State = state

    override fun loadState(state: State) {
        state.defaultBackend = state.backend().persistentValue
        this.state = state
    }

    companion object {
        fun getInstance(): AetherSettingsState =
            ApplicationManager.getApplication().getService(AetherSettingsState::class.java)
    }
}
