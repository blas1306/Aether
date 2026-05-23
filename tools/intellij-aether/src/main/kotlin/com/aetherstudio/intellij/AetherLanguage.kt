package com.aetherstudio.intellij

import com.intellij.lang.Language
import com.intellij.openapi.fileTypes.LanguageFileType
import com.intellij.openapi.util.IconLoader
import javax.swing.Icon

object AetherLanguage : Language("Aether")

object AetherIcons {
    val FILE: Icon = IconLoader.getIcon("/icons/aether.svg", AetherIcons::class.java)
}

object AetherFileType : LanguageFileType(AetherLanguage) {
    override fun getName(): String = "Aether"
    override fun getDescription(): String = "Aether script"
    override fun getDefaultExtension(): String = "ae"
    override fun getIcon(): Icon = AetherIcons.FILE
}
