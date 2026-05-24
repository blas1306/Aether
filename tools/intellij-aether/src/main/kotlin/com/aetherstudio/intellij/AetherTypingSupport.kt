package com.aetherstudio.intellij

object AetherTypingSupport {
    const val indentUnit: String = "    "
    val closingBraces: Set<Char> = setOf(')', ']', '}')

    data class EnterInsertion(val text: String, val caretShift: Int)

    fun matchingClosing(opening: Char): Char? =
        when (opening) {
            '(' -> ')'
            '[' -> ']'
            '{' -> '}'
            else -> null
        }

    fun enterBetweenBracesInsertion(text: CharSequence, offset: Int, indentUnit: String = this.indentUnit): EnterInsertion? {
        if (offset <= 0 || offset >= text.length) {
            return null
        }
        if (text[offset - 1] != '{' || text[offset] != '}') {
            return null
        }

        val currentIndent = leadingIndentForOffset(text, offset)
        val innerIndent = currentIndent + indentUnit
        val insertion = "\n$innerIndent\n$currentIndent"
        return EnterInsertion(insertion, 1 + innerIndent.length)
    }

    fun leadingIndentForOffset(text: CharSequence, offset: Int): String {
        val lineStart = lineStartOffset(text, offset)
        val builder = StringBuilder()
        var index = lineStart
        while (index < text.length && index < offset) {
            val char = text[index]
            if (char != ' ' && char != '\t') {
                break
            }
            builder.append(char)
            index++
        }
        return builder.toString()
    }

    private fun lineStartOffset(text: CharSequence, offset: Int): Int {
        var index = minOf(offset, text.length) - 1
        while (index >= 0) {
            if (text[index] == '\n') {
                return index + 1
            }
            index--
        }
        return 0
    }
}
