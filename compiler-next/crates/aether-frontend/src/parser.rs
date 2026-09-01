//! Recursive-descent parser for the deliberately closed Vertical-3 grammar.

use crate::{
    AstAlias, AstBinaryOp, AstBlock, AstExpr, AstExprKind, AstFunction, AstImport, AstParameter,
    AstStmt, AstStmtKind, AstType, AstUnaryOp, Diagnostic, DiagnosticCategory, ParsedAst, Phase,
    SourceFile, Token, TokenKind,
};

/// Parses an already tokenized source file.
pub fn parse(_source: &SourceFile, tokens: Vec<Token>) -> Result<ParsedAst, Vec<Diagnostic>> {
    let mut parser = Parser { tokens, cursor: 0 };
    let mut imports = Vec::new();
    while parser.at(TokenKind::KwImport) {
        match parser.import() {
            Ok(import) => imports.push(import),
            Err(error) => return Err(vec![error]),
        }
    }
    let mut aliases = Vec::new();
    let mut functions = Vec::new();
    while !parser.at(TokenKind::Eof) {
        if parser.at(TokenKind::KwAlias) {
            match parser.alias() {
                Ok(alias) => aliases.push(alias),
                Err(error) => return Err(vec![error]),
            }
        } else {
            match parser.function() {
                Ok(function) => functions.push(function),
                Err(error) => return Err(vec![error]),
            }
        }
    }
    if functions.is_empty() {
        Err(vec![parser.error(
            "E0101",
            "expected at least one function declaration",
        )])
    } else {
        Ok(ParsedAst {
            imports,
            aliases,
            functions,
        })
    }
}

struct Parser {
    tokens: Vec<Token>,
    cursor: usize,
}

impl Parser {
    fn alias(&mut self) -> Result<AstAlias, Diagnostic> {
        let start = self.expect(TokenKind::KwAlias, "expected `alias`")?.span;
        let name = self
            .expect(TokenKind::Identifier, "expected alias name")?
            .lexeme;
        self.expect(TokenKind::Equal, "expected `=` in alias declaration")?;
        let target = self.ty()?;
        let end = self
            .expect(TokenKind::Semicolon, "expected `;` after alias declaration")?
            .span;
        Ok(AstAlias {
            name,
            target,
            span: start.through(end),
        })
    }

    fn import(&mut self) -> Result<AstImport, Diagnostic> {
        let start = self.expect(TokenKind::KwImport, "expected `import`")?.span;
        let module = self
            .expect(TokenKind::Identifier, "expected module name after `import`")?
            .lexeme;
        let end = self
            .expect(
                TokenKind::Semicolon,
                "expected `;` after module import; selective, aliased and nested imports are not admitted",
            )?
            .span;
        Ok(AstImport {
            module,
            span: start.through(end),
        })
    }

    fn function(&mut self) -> Result<AstFunction, Diagnostic> {
        let start = self.current().span;
        let return_type = self.ty()?;
        let name = self
            .expect(TokenKind::Identifier, "expected function name")?
            .lexeme;
        self.expect(TokenKind::LeftParen, "expected `(` after function name")?;
        let mut parameters = Vec::new();
        if !self.at(TokenKind::RightParen) {
            loop {
                let parameter_start = self.current().span;
                let ty = self.ty()?;
                let token = self.expect(TokenKind::Identifier, "expected parameter name")?;
                parameters.push(AstParameter {
                    ty,
                    name: token.lexeme,
                    span: parameter_start.through(token.span),
                });
                if self.consume(TokenKind::Comma).is_none() {
                    break;
                }
                if self.at(TokenKind::RightParen) {
                    return Err(self.error("E0104", "expected parameter after `,`"));
                }
            }
        }
        self.expect(TokenKind::RightParen, "expected `)` after parameters")?;
        let body = self.block()?;
        Ok(AstFunction {
            return_type,
            name,
            parameters,
            span: start.through(body.span),
            body,
        })
    }

    fn ty(&mut self) -> Result<AstType, Diagnostic> {
        let token = match self.current().kind {
            TokenKind::KwInt | TokenKind::KwBool | TokenKind::Identifier => self.advance(),
            _ => return Err(self.error("E0100", "expected type name")),
        };
        Ok(AstType {
            name: token.lexeme,
            span: token.span,
        })
    }

    fn block(&mut self) -> Result<AstBlock, Diagnostic> {
        let left = self.expect(TokenKind::LeftBrace, "expected `{`")?;
        let mut statements = Vec::new();
        while !self.at(TokenKind::RightBrace) && !self.at(TokenKind::Eof) {
            statements.push(self.statement()?);
        }
        let right = self.expect(TokenKind::RightBrace, "expected `}` to close block")?;
        Ok(AstBlock {
            statements,
            span: left.span.through(right.span),
        })
    }

    fn statement(&mut self) -> Result<AstStmt, Diagnostic> {
        let start = self.current().span;
        let kind = match self.current().kind {
            TokenKind::KwInt | TokenKind::KwBool => {
                let ty = self.ty()?;
                let name = self
                    .expect(TokenKind::Identifier, "expected local name")?
                    .lexeme;
                self.expect(TokenKind::Equal, "locals require an initializer")?;
                let initializer = self.expression()?;
                AstStmtKind::Local {
                    ty,
                    name,
                    initializer,
                }
            }
            TokenKind::Identifier if self.peek_kind(1) == TokenKind::Identifier => {
                let ty = self.ty()?;
                let name = self
                    .expect(TokenKind::Identifier, "expected local name")?
                    .lexeme;
                self.expect(TokenKind::Equal, "locals require an initializer")?;
                let initializer = self.expression()?;
                AstStmtKind::Local {
                    ty,
                    name,
                    initializer,
                }
            }
            TokenKind::Identifier => {
                let name = self.advance().lexeme;
                self.expect(
                    TokenKind::Equal,
                    "only assignment statements are admitted here",
                )?;
                let value = self.expression()?;
                AstStmtKind::Assign { name, value }
            }
            TokenKind::KwReturn => {
                self.advance();
                AstStmtKind::Return(self.expression()?)
            }
            TokenKind::KwIf => {
                self.advance();
                self.expect(TokenKind::LeftParen, "expected `(` after `if`")?;
                let condition = self.expression()?;
                self.expect(TokenKind::RightParen, "expected `)` after condition")?;
                let then_block = self.block()?;
                let else_block = if self.consume(TokenKind::KwElse).is_some() {
                    Some(self.block()?)
                } else {
                    None
                };
                let end = else_block
                    .as_ref()
                    .map_or(then_block.span, |block| block.span);
                return Ok(AstStmt {
                    kind: AstStmtKind::If {
                        condition,
                        then_block,
                        else_block,
                    },
                    span: start.through(end),
                });
            }
            TokenKind::KwWhile => {
                self.advance();
                self.expect(TokenKind::LeftParen, "expected `(` after `while`")?;
                let condition = self.expression()?;
                self.expect(TokenKind::RightParen, "expected `)` after condition")?;
                let body = self.block()?;
                return Ok(AstStmt {
                    kind: AstStmtKind::While {
                        condition,
                        body: body.clone(),
                    },
                    span: start.through(body.span),
                });
            }
            _ => return Err(self.error("E0102", "expected a Vertical-3 statement")),
        };
        let semicolon = self.expect(TokenKind::Semicolon, "expected `;` after statement")?;
        Ok(AstStmt {
            kind,
            span: start.through(semicolon.span),
        })
    }

    fn expression(&mut self) -> Result<AstExpr, Diagnostic> {
        self.equality()
    }

    fn equality(&mut self) -> Result<AstExpr, Diagnostic> {
        let mut expr = self.comparison()?;
        loop {
            let op = if self.consume(TokenKind::EqualEqual).is_some() {
                Some(AstBinaryOp::Equal)
            } else if self.consume(TokenKind::BangEqual).is_some() {
                Some(AstBinaryOp::NotEqual)
            } else {
                None
            };
            let Some(op) = op else { break };
            let right = self.comparison()?;
            let span = expr.span.through(right.span);
            expr = AstExpr {
                kind: AstExprKind::Binary {
                    op,
                    left: Box::new(expr),
                    right: Box::new(right),
                },
                span,
            };
        }
        Ok(expr)
    }

    fn comparison(&mut self) -> Result<AstExpr, Diagnostic> {
        let mut expr = self.term()?;
        loop {
            let op = match self.current().kind {
                TokenKind::Less => Some(AstBinaryOp::Less),
                TokenKind::LessEqual => Some(AstBinaryOp::LessEqual),
                TokenKind::Greater => Some(AstBinaryOp::Greater),
                TokenKind::GreaterEqual => Some(AstBinaryOp::GreaterEqual),
                _ => None,
            };
            let Some(op) = op else { break };
            self.advance();
            let right = self.term()?;
            let span = expr.span.through(right.span);
            expr = AstExpr {
                kind: AstExprKind::Binary {
                    op,
                    left: Box::new(expr),
                    right: Box::new(right),
                },
                span,
            };
        }
        Ok(expr)
    }

    fn term(&mut self) -> Result<AstExpr, Diagnostic> {
        let mut expr = self.factor()?;
        loop {
            let op = match self.current().kind {
                TokenKind::Plus => Some(AstBinaryOp::Add),
                TokenKind::Minus => Some(AstBinaryOp::Subtract),
                _ => None,
            };
            let Some(op) = op else { break };
            self.advance();
            let right = self.factor()?;
            let span = expr.span.through(right.span);
            expr = AstExpr {
                kind: AstExprKind::Binary {
                    op,
                    left: Box::new(expr),
                    right: Box::new(right),
                },
                span,
            };
        }
        Ok(expr)
    }

    fn factor(&mut self) -> Result<AstExpr, Diagnostic> {
        let mut expr = self.unary()?;
        while self.consume(TokenKind::Star).is_some() {
            let right = self.unary()?;
            let span = expr.span.through(right.span);
            expr = AstExpr {
                kind: AstExprKind::Binary {
                    op: AstBinaryOp::Multiply,
                    left: Box::new(expr),
                    right: Box::new(right),
                },
                span,
            };
        }
        Ok(expr)
    }

    fn unary(&mut self) -> Result<AstExpr, Diagnostic> {
        if let Some(minus) = self.consume(TokenKind::Minus) {
            let operand = self.unary()?;
            let span = minus.span.through(operand.span);
            Ok(AstExpr {
                kind: AstExprKind::Unary {
                    op: AstUnaryOp::Negate,
                    operand: Box::new(operand),
                },
                span,
            })
        } else {
            self.primary()
        }
    }

    fn primary(&mut self) -> Result<AstExpr, Diagnostic> {
        let token = self.advance();
        let kind = match token.kind {
            TokenKind::Integer => AstExprKind::Integer(token.lexeme),
            TokenKind::Float => AstExprKind::Float(token.lexeme),
            TokenKind::KwTrue => AstExprKind::Bool(true),
            TokenKind::KwFalse => AstExprKind::Bool(false),
            TokenKind::Identifier if self.consume(TokenKind::Dot).is_some() => {
                let member =
                    self.expect(TokenKind::Identifier, "expected function name after `.`")?;
                if self.consume(TokenKind::LeftParen).is_some() {
                    let (args, right) = self.arguments()?;
                    return Ok(AstExpr {
                        kind: AstExprKind::QualifiedCall {
                            module: token.lexeme,
                            function: member.lexeme,
                            args,
                        },
                        span: token.span.through(right),
                    });
                }
                return Ok(AstExpr {
                    kind: AstExprKind::QualifiedName {
                        module: token.lexeme,
                        member: member.lexeme,
                    },
                    span: token.span.through(member.span),
                });
            }
            TokenKind::Identifier if self.consume(TokenKind::LeftParen).is_some() => {
                let (args, right) = self.arguments()?;
                return Ok(AstExpr {
                    kind: AstExprKind::Call {
                        callee: token.lexeme,
                        args,
                    },
                    span: token.span.through(right),
                });
            }
            TokenKind::Identifier => AstExprKind::Name(token.lexeme),
            TokenKind::LeftParen => {
                let expr = self.expression()?;
                let right = self.expect(TokenKind::RightParen, "expected `)` after expression")?;
                return Ok(AstExpr {
                    span: token.span.through(right.span),
                    ..expr
                });
            }
            _ => {
                return Err(Diagnostic::new(
                    "E0103",
                    Phase::Parse,
                    DiagnosticCategory::Syntax,
                    "expected expression",
                    Some(token.span),
                ));
            }
        };
        Ok(AstExpr {
            kind,
            span: token.span,
        })
    }

    fn arguments(&mut self) -> Result<(Vec<AstExpr>, crate::Span), Diagnostic> {
        let mut args = Vec::new();
        if !self.at(TokenKind::RightParen) {
            loop {
                args.push(self.expression()?);
                if self.consume(TokenKind::Comma).is_none() {
                    break;
                }
                if self.at(TokenKind::RightParen) {
                    return Err(self.error("E0104", "expected argument after `,`"));
                }
            }
        }
        let right = self.expect(TokenKind::RightParen, "expected `)` after arguments")?;
        Ok((args, right.span))
    }

    fn current(&self) -> &Token {
        &self.tokens[self.cursor.min(self.tokens.len() - 1)]
    }

    fn at(&self, kind: TokenKind) -> bool {
        self.current().kind == kind
    }

    fn peek_kind(&self, offset: usize) -> TokenKind {
        self.tokens
            .get(self.cursor + offset)
            .map_or(TokenKind::Eof, |token| token.kind)
    }

    fn advance(&mut self) -> Token {
        let token = self.current().clone();
        if token.kind != TokenKind::Eof {
            self.cursor += 1;
        }
        token
    }

    fn consume(&mut self, kind: TokenKind) -> Option<Token> {
        self.at(kind).then(|| self.advance())
    }

    fn expect(&mut self, kind: TokenKind, message: &'static str) -> Result<Token, Diagnostic> {
        self.consume(kind)
            .ok_or_else(|| self.error("E0100", message))
    }

    fn error(&self, code: &'static str, message: impl Into<String>) -> Diagnostic {
        Diagnostic::new(
            code,
            Phase::Parse,
            DiagnosticCategory::Syntax,
            message,
            Some(self.current().span),
        )
    }
}

#[cfg(test)]
mod tests {
    use crate::{AstStmtKind, SourceFile, parse_source};

    #[test]
    fn parses_loop_program() {
        let source = SourceFile::new("loop.ae", "int main(){int i=0;while(i<3){i=i+1;}return i;}");
        let ast = parse_source(&source).unwrap();
        assert_eq!(ast.functions()[0].body.statements.len(), 3);
        assert!(matches!(
            ast.functions()[0].body.statements[1].kind,
            AstStmtKind::While { .. }
        ));
    }

    #[test]
    fn parses_multiple_functions_parameters_and_calls() {
        let source = SourceFile::new(
            "calls.ae",
            "int add(int a,int b){return a+b;}int main(){return add(20,22);}",
        );
        let ast = parse_source(&source).unwrap();
        assert_eq!(ast.functions().len(), 2);
        assert_eq!(ast.functions()[0].parameters.len(), 2);
    }

    #[test]
    fn malformed_syntax_is_structured() {
        let error =
            parse_source(&SourceFile::new("bad.ae", "int main( { return 0; }")).unwrap_err();
        assert_eq!(error[0].phase, crate::Phase::Parse);
        assert!(error[0].span.is_some());
    }
}
