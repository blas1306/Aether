package com.aetherstudio.intellij

import com.intellij.lexer.LexerBase
import com.intellij.psi.TokenType
import com.intellij.psi.tree.IElementType

class AetherHighlightingLexer : LexerBase() {
    private var buffer: CharSequence = ""
    private var startOffset: Int = 0
    private var endOffset: Int = 0
    private var tokenStart: Int = 0
    private var tokenEnd: Int = 0
    private var tokenType: IElementType? = null

    override fun start(buffer: CharSequence, startOffset: Int, endOffset: Int, initialState: Int) {
        this.buffer = buffer
        this.startOffset = startOffset
        this.endOffset = endOffset
        tokenStart = startOffset
        tokenEnd = startOffset
        advance()
    }

    override fun getState(): Int = 0
    override fun getTokenType(): IElementType? = tokenType
    override fun getTokenStart(): Int = tokenStart
    override fun getTokenEnd(): Int = tokenEnd
    override fun getBufferSequence(): CharSequence = buffer
    override fun getBufferEnd(): Int = endOffset

    override fun advance() {
        tokenStart = tokenEnd
        if (tokenStart >= endOffset) {
            tokenType = null
            return
        }

        val char = buffer[tokenStart]
        when {
            char.isWhitespace() -> consumeWhitespace()
            char == '#' -> consumeLineComment()
            char == '/' && tokenStart + 1 < endOffset && buffer[tokenStart + 1] == '/' -> consumeLineComment()
            char == '"' -> consumeString()
            char.isDigit() -> consumeNumber()
            char.isIdentifierStart() -> consumeIdentifier()
            char.isOperatorOrPunctuation() -> {
                tokenEnd = tokenStart + 1
                tokenType = AetherTokenTypes.OPERATOR
            }
            else -> {
                tokenEnd = tokenStart + 1
                tokenType = AetherTokenTypes.BAD_CHARACTER
            }
        }
    }

    private fun consumeWhitespace() {
        tokenEnd = tokenStart + 1
        while (tokenEnd < endOffset && buffer[tokenEnd].isWhitespace()) {
            tokenEnd++
        }
        tokenType = TokenType.WHITE_SPACE
    }

    private fun consumeLineComment() {
        tokenEnd = tokenStart + 1
        while (tokenEnd < endOffset && buffer[tokenEnd] != '\n') {
            tokenEnd++
        }
        tokenType = AetherTokenTypes.COMMENT
    }

    private fun consumeString() {
        tokenEnd = tokenStart + 1
        var escaped = false
        while (tokenEnd < endOffset) {
            val char = buffer[tokenEnd]
            tokenEnd++
            if (escaped) {
                escaped = false
            } else if (char == '\\') {
                escaped = true
            } else if (char == '"') {
                break
            }
        }
        tokenType = AetherTokenTypes.STRING
    }

    private fun consumeNumber() {
        tokenEnd = tokenStart + 1
        while (tokenEnd < endOffset && (buffer[tokenEnd].isDigit() || buffer[tokenEnd] == '.')) {
            tokenEnd++
        }
        tokenType = AetherTokenTypes.NUMBER
    }

    private fun consumeIdentifier() {
        tokenEnd = tokenStart + 1
        while (tokenEnd < endOffset && buffer[tokenEnd].isIdentifierPart()) {
            tokenEnd++
        }
        val text = buffer.subSequence(tokenStart, tokenEnd).toString()
        tokenType = if (text in AetherTokenTypes.KEYWORDS) AetherTokenTypes.KEYWORD else AetherTokenTypes.IDENTIFIER
    }

    private fun Char.isIdentifierStart(): Boolean = this == '_' || isLetter()
    private fun Char.isIdentifierPart(): Boolean = isIdentifierStart() || isDigit()
    private fun Char.isOperatorOrPunctuation(): Boolean = this in "()[]{}.,:;+-*/\\%=!<>|&"
}
