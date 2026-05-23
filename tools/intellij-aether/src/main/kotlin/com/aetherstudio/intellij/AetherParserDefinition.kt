package com.aetherstudio.intellij

import com.intellij.lang.ASTNode
import com.intellij.lang.ParserDefinition
import com.intellij.lang.PsiParser
import com.intellij.lang.PsiBuilder
import com.intellij.lexer.Lexer
import com.intellij.openapi.project.Project
import com.intellij.psi.FileViewProvider
import com.intellij.psi.PsiElement
import com.intellij.psi.PsiFile
import com.intellij.psi.TokenType
import com.intellij.psi.tree.IFileElementType
import com.intellij.psi.tree.TokenSet
import com.intellij.extapi.psi.PsiFileBase

object AetherElementTypes {
    val FILE = IFileElementType(AetherLanguage)
}

class AetherParserDefinition : ParserDefinition {
    override fun createLexer(project: Project?): Lexer = AetherHighlightingLexer()

    override fun createParser(project: Project?): PsiParser = PsiParser { root, builder ->
        val file = builder.mark()
        while (!builder.eof()) {
            builder.advanceLexer()
        }
        file.done(root)
        builder.treeBuilt
    }

    override fun getFileNodeType(): IFileElementType = AetherElementTypes.FILE
    override fun getWhitespaceTokens(): TokenSet = TokenSet.create(TokenType.WHITE_SPACE)
    override fun getCommentTokens(): TokenSet = TokenSet.create(AetherTokenTypes.COMMENT)
    override fun getStringLiteralElements(): TokenSet = TokenSet.create(AetherTokenTypes.STRING)
    override fun createElement(node: ASTNode): PsiElement = AetherPsiElement(node)
    override fun createFile(viewProvider: FileViewProvider): PsiFile = AetherPsiFile(viewProvider)
}

private class AetherPsiElement(node: ASTNode) : com.intellij.extapi.psi.ASTWrapperPsiElement(node)

class AetherPsiFile(viewProvider: FileViewProvider) : PsiFileBase(viewProvider, AetherLanguage) {
    override fun getFileType(): AetherFileType = AetherFileType
    override fun toString(): String = "Aether File"
}
