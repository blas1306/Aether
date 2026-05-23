package com.aetherstudio.intellij

import com.intellij.openapi.application.ApplicationManager
import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage

@State(name = "AetherSettings", storages = [Storage("aether.xml")])
class AetherSettingsState : PersistentStateComponent<AetherSettingsState.State> {
    data class State(var pythonPath: String = "")

    private var state = State()

    override fun getState(): State = state

    override fun loadState(state: State) {
        this.state = state
    }

    companion object {
        fun getInstance(): AetherSettingsState =
            ApplicationManager.getApplication().getService(AetherSettingsState::class.java)
    }
}
