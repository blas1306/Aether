//! Recursive-descent parser for the deliberately closed Vertical-7 grammar.

use crate::{
    AstAlias, AstBinaryOp, AstBlock, AstEnum, AstExpr, AstExprKind, AstField, AstFunction,
    AstImport, AstMatchArm, AstParameter, AstPlace, AstStmt, AstStmtKind, AstStruct, AstType,
    AstUnaryOp, AstVariant, AstVariantPattern, Diagnostic, DiagnosticCategory, ParsedAst, Phase,
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
    let mut structs = Vec::new();
    let mut enums = Vec::new();
    let mut functions = Vec::new();
    while !parser.at(TokenKind::Eof) {
        if parser.at(TokenKind::KwAlias) {
            match parser.alias() {
                Ok(alias) => aliases.push(alias),
                Err(error) => return Err(vec![error]),
            }
        } else if parser.at(TokenKind::KwStruct) {
            match parser.struct_decl() {
                Ok(struct_decl) => structs.push(struct_decl),
                Err(error) => return Err(vec![error]),
            }
        } else if parser.at(TokenKind::KwEnum) {
            match parser.enum_decl() {
                Ok(enum_decl) => enums.push(enum_decl),
                Err(error) => return Err(vec![error]),
            }
        } else {
            match parser.function() {
                Ok(function) => functions.push(function),
                Err(error) => return Err(vec![error]),
            }
        }
    }
    if aliases.is_empty() && structs.is_empty() && enums.is_empty() && functions.is_empty() {
        Err(vec![parser.error(
            "E0101",
            "expected at least one top-level declaration",
        )])
    } else {
        Ok(ParsedAst {
            imports,
            aliases,
            structs,
            enums,
            functions,
        })
    }
}

struct Parser {
    tokens: Vec<Token>,
    cursor: usize,
}

impl Parser {
    fn enum_decl(&mut self) -> Result<AstEnum, Diagnostic> {
        let start = self.expect(TokenKind::KwEnum, "expected `enum`")?.span;
        let name = self
            .expect(TokenKind::Identifier, "expected enum name")?
            .lexeme;
        self.expect(TokenKind::LeftBrace, "expected `{` after enum name")?;
        let mut variants = Vec::new();
        while !self.at(TokenKind::RightBrace) && !self.at(TokenKind::Eof) {
            let variant = self.expect(TokenKind::Identifier, "expected variant name")?;
            let mut payloads = Vec::new();
            let mut end = variant.span;
            if self.consume(TokenKind::LeftParen).is_some() {
                if self.at(TokenKind::RightParen) {
                    return Err(
                        self.error("E0105", "empty variant payload list is invalid; omit `()`")
                    );
                }
                loop {
                    payloads.push(self.ty()?);
                    if self.consume(TokenKind::Comma).is_none() {
                        break;
                    }
                    if self.at(TokenKind::RightParen) {
                        return Err(self.error("E0105", "expected payload type after `,`"));
                    }
                }
                end = self
                    .expect(TokenKind::RightParen, "expected `)` after variant payloads")?
                    .span;
            }
            variants.push(AstVariant {
                name: variant.lexeme,
                payloads,
                span: variant.span.through(end),
            });
            if self.consume(TokenKind::Comma).is_none() && !self.at(TokenKind::RightBrace) {
                return Err(self.error("E0105", "expected `,` after enum variant"));
            }
        }
        if variants.is_empty() {
            return Err(self.error("E0105", "enum requires at least one variant"));
        }
        let end = self
            .expect(TokenKind::RightBrace, "expected `}` to close enum")?
            .span;
        Ok(AstEnum {
            name,
            variants,
            span: start.through(end),
        })
    }

    fn struct_decl(&mut self) -> Result<AstStruct, Diagnostic> {
        let start = self.expect(TokenKind::KwStruct, "expected `struct`")?.span;
        let name = self
            .expect(TokenKind::Identifier, "expected struct name")?
            .lexeme;
        self.expect(TokenKind::LeftBrace, "expected `{` after struct name")?;
        let mut fields = Vec::new();
        while !self.at(TokenKind::RightBrace) && !self.at(TokenKind::Eof) {
            let field_start = self.current().span;
            let ty = self.ty()?;
            let field = self.expect(TokenKind::Identifier, "expected field name")?;
            let end = self.expect(TokenKind::Semicolon, "expected `;` after field")?;
            fields.push(AstField {
                ty,
                name: field.lexeme,
                span: field_start.through(end.span),
            });
        }
        let end = self.expect(TokenKind::RightBrace, "expected `}` to close struct")?;
        Ok(AstStruct {
            name,
            fields,
            span: start.through(end.span),
        })
    }

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
        let (module, name, span) =
            if token.kind == TokenKind::Identifier && self.consume(TokenKind::Dot).is_some() {
                let member = self.expect(TokenKind::Identifier, "expected type name after `.`")?;
                (
                    Some(token.lexeme),
                    member.lexeme,
                    token.span.through(member.span),
                )
            } else {
                (None, token.lexeme, token.span)
            };
        Ok(AstType { module, name, span })
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

    #[allow(clippy::too_many_lines)]
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
            TokenKind::Identifier
                if self.peek_kind(1) == TokenKind::Identifier
                    || (self.peek_kind(1) == TokenKind::Dot
                        && self.peek_kind(2) == TokenKind::Identifier
                        && self.peek_kind(3) == TokenKind::Identifier) =>
            {
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
                let root = self.advance();
                let mut fields = Vec::new();
                let mut end = root.span;
                while self.consume(TokenKind::Dot).is_some() {
                    let field =
                        self.expect(TokenKind::Identifier, "expected field name after `.`")?;
                    end = field.span;
                    fields.push((field.lexeme, field.span));
                }
                self.expect(
                    TokenKind::Equal,
                    "only assignment statements are admitted here",
                )?;
                let value = self.expression()?;
                AstStmtKind::Assign {
                    place: AstPlace {
                        root: root.lexeme,
                        fields,
                        span: root.span.through(end),
                    },
                    value,
                }
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
            TokenKind::KwMatch => return self.match_statement(start),
            _ => return Err(self.error("E0102", "expected a Vertical-7 statement")),
        };
        let semicolon = self.expect(TokenKind::Semicolon, "expected `;` after statement")?;
        Ok(AstStmt {
            kind,
            span: start.through(semicolon.span),
        })
    }

    fn match_statement(&mut self, start: crate::Span) -> Result<AstStmt, Diagnostic> {
        self.expect(TokenKind::KwMatch, "expected `match`")?;
        self.expect(TokenKind::LeftParen, "expected `(` after `match`")?;
        let scrutinee = self.expression()?;
        self.expect(TokenKind::RightParen, "expected `)` after match scrutinee")?;
        self.expect(TokenKind::LeftBrace, "expected `{` before match arms")?;
        let mut arms = Vec::new();
        while !self.at(TokenKind::RightBrace) && !self.at(TokenKind::Eof) {
            let pattern = self.variant_pattern()?;
            self.expect(TokenKind::FatArrow, "expected `=>` after variant pattern")?;
            let body = self.block()?;
            let span = pattern.span.through(body.span);
            arms.push(AstMatchArm {
                pattern,
                body,
                span,
            });
        }
        let right = self
            .expect(TokenKind::RightBrace, "expected `}` after match arms")?
            .span;
        Ok(AstStmt {
            kind: AstStmtKind::Match { scrutinee, arms },
            span: start.through(right),
        })
    }

    fn variant_pattern(&mut self) -> Result<AstVariantPattern, Diagnostic> {
        let first = self.expect(TokenKind::Identifier, "expected enum name in pattern")?;
        self.expect(TokenKind::Dot, "variant patterns must be qualified")?;
        let second = self.expect(TokenKind::Identifier, "expected variant name after `.`")?;
        let (module, enum_name, variant, mut end) = if self.consume(TokenKind::Dot).is_some() {
            let third = self.expect(TokenKind::Identifier, "expected variant name after `.`")?;
            (Some(first.lexeme), second.lexeme, third.lexeme, third.span)
        } else {
            (None, first.lexeme, second.lexeme, second.span)
        };
        let mut bindings = Vec::new();
        if self.consume(TokenKind::LeftParen).is_some() {
            if !self.at(TokenKind::RightParen) {
                loop {
                    let binding = self.expect(TokenKind::Identifier, "expected payload binding")?;
                    bindings.push((binding.lexeme, binding.span));
                    if self.consume(TokenKind::Comma).is_none() {
                        break;
                    }
                    if self.at(TokenKind::RightParen) {
                        return Err(self.error("E0106", "expected payload binding after `,`"));
                    }
                }
            }
            end = self
                .expect(TokenKind::RightParen, "expected `)` after payload bindings")?
                .span;
        }
        Ok(AstVariantPattern {
            module,
            enum_name,
            variant,
            bindings,
            span: first.span.through(end),
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
        loop {
            let op = match self.current().kind {
                TokenKind::Star => AstBinaryOp::Multiply,
                TokenKind::Slash => AstBinaryOp::Divide,
                TokenKind::Percent => AstBinaryOp::Remainder,
                _ => break,
            };
            self.advance();
            let right = self.unary()?;
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

    #[allow(clippy::too_many_lines)]
    fn primary(&mut self) -> Result<AstExpr, Diagnostic> {
        let token = self.advance();
        let mut expr = match token.kind {
            TokenKind::Integer => AstExpr {
                kind: AstExprKind::Integer(token.lexeme),
                span: token.span,
            },
            TokenKind::Float => AstExpr {
                kind: AstExprKind::Float(token.lexeme),
                span: token.span,
            },
            TokenKind::KwTrue => AstExpr {
                kind: AstExprKind::Bool(true),
                span: token.span,
            },
            TokenKind::KwFalse => AstExpr {
                kind: AstExprKind::Bool(false),
                span: token.span,
            },
            TokenKind::Identifier if self.consume(TokenKind::Dot).is_some() => {
                let member =
                    self.expect(TokenKind::Identifier, "expected member name after `.`")?;
                if self.consume(TokenKind::Dot).is_some() {
                    let variant =
                        self.expect(TokenKind::Identifier, "expected variant name after `.`")?;
                    if self.consume(TokenKind::LeftParen).is_some() {
                        let (args, right) = self.arguments()?;
                        AstExpr {
                            kind: AstExprKind::VariantCall {
                                module: token.lexeme,
                                enum_name: member.lexeme,
                                variant: variant.lexeme,
                                args,
                            },
                            span: token.span.through(right),
                        }
                    } else {
                        let inner_span = token.span.through(member.span);
                        AstExpr {
                            kind: AstExprKind::Field {
                                base: Box::new(AstExpr {
                                    kind: AstExprKind::Field {
                                        base: Box::new(AstExpr {
                                            kind: AstExprKind::Name(token.lexeme),
                                            span: token.span,
                                        }),
                                        name: member.lexeme,
                                        name_span: member.span,
                                    },
                                    span: inner_span,
                                }),
                                name: variant.lexeme,
                                name_span: variant.span,
                            },
                            span: token.span.through(variant.span),
                        }
                    }
                } else if self.consume(TokenKind::LeftParen).is_some() {
                    let (args, right) = self.arguments()?;
                    AstExpr {
                        kind: AstExprKind::QualifiedCall {
                            module: token.lexeme,
                            function: member.lexeme,
                            args,
                        },
                        span: token.span.through(right),
                    }
                } else {
                    AstExpr {
                        kind: AstExprKind::Field {
                            base: Box::new(AstExpr {
                                kind: AstExprKind::Name(token.lexeme),
                                span: token.span,
                            }),
                            name: member.lexeme,
                            name_span: member.span,
                        },
                        span: token.span.through(member.span),
                    }
                }
            }
            TokenKind::Identifier | TokenKind::KwInt | TokenKind::KwBool
                if self.consume(TokenKind::LeftParen).is_some() =>
            {
                let (args, right) = self.arguments()?;
                AstExpr {
                    kind: AstExprKind::Call {
                        callee: token.lexeme,
                        args,
                    },
                    span: token.span.through(right),
                }
            }
            TokenKind::Identifier => AstExpr {
                kind: AstExprKind::Name(token.lexeme),
                span: token.span,
            },
            TokenKind::LeftParen => {
                let expr = self.expression()?;
                let right = self.expect(TokenKind::RightParen, "expected `)` after expression")?;
                AstExpr {
                    span: token.span.through(right.span),
                    ..expr
                }
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
        while self.consume(TokenKind::Dot).is_some() {
            let member = self.expect(TokenKind::Identifier, "expected field name after `.`")?;
            let span = expr.span.through(member.span);
            expr = AstExpr {
                kind: AstExprKind::Field {
                    base: Box::new(expr),
                    name: member.lexeme,
                    name_span: member.span,
                },
                span,
            };
        }
        Ok(expr)
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
