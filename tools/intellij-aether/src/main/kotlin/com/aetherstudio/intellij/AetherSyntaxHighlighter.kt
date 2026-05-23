package com.aetherstudio.intellij

import com.intellij.lexer.Lexer
import com.intellij.openapi.editor.DefaultLanguageHighlighterColors
import com.intellij.openapi.editor.HighlighterColors
import com.intellij.openapi.editor.colors.TextAttributesKey
import com.intellij.openapi.fileTypes.SyntaxHighlighterBase
import com.intellij.psi.tree.IElementType

class AetherSyntaxHighlighter : SyntaxHighlighterBase() {
    override fun getHighlightingLexer(): Lexer = AetherHighlightingLexer()

    override fun getTokenHighlights(tokenType: IElementType): Array<TextAttributesKey> =
        pack(
            when (tokenType) {
                AetherTokenTypes.KEYWORD -> KEYWORD
                AetherTokenTypes.STRING -> STRING
                AetherTokenTypes.NUMBER -> NUMBER
                AetherTokenTypes.COMMENT -> COMMENT
                AetherTokenTypes.OPERATOR -> OPERATOR
                AetherTokenTypes.BAD_CHARACTER -> BAD_CHARACTER
                else -> null
            }
        )

    companion object {
        private val KEYWORD = TextAttributesKey.createTextAttributesKey(
            "AETHER_KEYWORD",
            DefaultLanguageHighlighterColors.KEYWORD,
        )
        private val STRING = TextAttributesKey.createTextAttributesKey(
            "AETHER_STRING",
            DefaultLanguageHighlighterColors.STRING,
        )
        private val NUMBER = TextAttributesKey.createTextAttributesKey(
            "AETHER_NUMBER",
            DefaultLanguageHighlighterColors.NUMBER,
        )
        private val COMMENT = TextAttributesKey.createTextAttributesKey(
            "AETHER_COMMENT",
            DefaultLanguageHighlighterColors.LINE_COMMENT,
        )
        private val OPERATOR = TextAttributesKey.createTextAttributesKey(
            "AETHER_OPERATOR",
            DefaultLanguageHighlighterColors.OPERATION_SIGN,
        )
        private val BAD_CHARACTER = TextAttributesKey.createTextAttributesKey(
            "AETHER_BAD_CHARACTER",
            HighlighterColors.BAD_CHARACTER,
        )
    }
}
