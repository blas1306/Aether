package com.aetherstudio.intellij

import com.intellij.psi.tree.IElementType

object AetherTokenTypes {
    val KEYWORD = IElementType("AETHER_KEYWORD", AetherLanguage)
    val STRING = IElementType("AETHER_STRING", AetherLanguage)
    val NUMBER = IElementType("AETHER_NUMBER", AetherLanguage)
    val COMMENT = IElementType("AETHER_COMMENT", AetherLanguage)
    val IDENTIFIER = IElementType("AETHER_IDENTIFIER", AetherLanguage)
    val OPERATOR = IElementType("AETHER_OPERATOR", AetherLanguage)
    val BAD_CHARACTER = IElementType("AETHER_BAD_CHARACTER", AetherLanguage)

    val KEYWORDS = setOf(
        "&&",
        "||",
        "alias",
        "as",
        "boolean",
        "break",
        "const",
        "continue",
        "double",
        "else",
        "false",
        "float",
        "for",
        "function",
        "if",
        "import",
        "in",
        "int",
        "Matrix",
        "not",
        "null",
        "package",
        "private",
        "public",
        "return",
        "string",
        "struct",
        "true",
        "Vector",
        "void",
        "while",
    )
}
