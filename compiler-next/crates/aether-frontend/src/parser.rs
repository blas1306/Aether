//! Recursive-descent parser for the deliberately closed Vertical-16 grammar.

use crate::{
    AstAlias, AstBinaryOp, AstBlock, AstCapabilityConstraint, AstCatch, AstEnum, AstExpr,
    AstExprKind, AstField, AstFunction, AstGenericParam, AstImport, AstMatchArm, AstMatchMode,
    AstParameter, AstReferenceType, AstStmt, AstStmtKind, AstStruct, AstType, AstUnaryOp,
    AstVariant, AstVariantPattern, Diagnostic, DiagnosticCategory, ParsedAst, Phase, SourceFile,
    Token, TokenKind,
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
    let mut classes = Vec::new();
    let mut interfaces = Vec::new();
    while !parser.at(TokenKind::Eof) {
        if parser.current().lexeme == "interface"
            || (parser.current().lexeme == "public"
                && parser
                    .tokens
                    .get(parser.cursor + 1)
                    .is_some_and(|t| t.lexeme == "interface"))
        {
            match parser.interface_decl() {
                Ok(i) => interfaces.push(i),
                Err(e) => return Err(vec![e]),
            }
        } else if parser.current().lexeme == "class"
            || parser.current().lexeme == "public"
            || parser.current().lexeme == "open"
        {
            match parser.class_decl() {
                Ok(class) => classes.push(class),
                Err(error) => return Err(vec![error]),
            }
        } else if parser.at(TokenKind::KwAlias) {
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
    if interfaces.is_empty()
        && classes.is_empty()
        && aliases.is_empty()
        && structs.is_empty()
        && enums.is_empty()
        && functions.is_empty()
    {
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
            classes,
            interfaces,
        })
    }
}

struct Parser {
    tokens: Vec<Token>,
    cursor: usize,
}

impl Parser {
    fn interface_decl(&mut self) -> Result<crate::AstInterface, Diagnostic> {
        let start = self.current().span;
        let public = self.current().lexeme == "public";
        if public {
            self.advance();
        }
        self.advance();
        let name = self
            .expect(TokenKind::Identifier, "expected interface name")?
            .lexeme;
        self.expect(
            TokenKind::LeftBrace,
            "flat interface requires `{`; generics and inheritance are unavailable",
        )?;
        let mut requirements = Vec::new();
        while !self.at(TokenKind::RightBrace) && !self.at(TokenKind::Eof) {
            if self.current().lexeme == "public" {
                self.advance();
            }
            let mutable = self.consume(TokenKind::KwMut).is_some();
            let span = self.current().span;
            if matches!(
                self.current().lexeme.as_str(),
                "private"
                    | "static"
                    | "abstract"
                    | "override"
                    | "open"
                    | "init"
                    | "deinit"
                    | "protected"
            ) {
                return Err(self.error(
                    "E0410",
                    "unsupported interface member; requirements are implicitly public",
                ));
            }
            let result = self.ty()?;
            let method = self
                .expect(TokenKind::Identifier, "expected requirement name")?
                .lexeme;
            self.expect(
                TokenKind::LeftParen,
                "interface members must be non-generic method requirements",
            )?;
            let mut parameters = Vec::new();
            if !self.at(TokenKind::RightParen) {
                loop {
                    let ty = self.ty()?;
                    let token = self.expect(TokenKind::Identifier, "expected parameter name")?;
                    parameters.push(AstParameter {
                        ty,
                        name: token.lexeme,
                        span: token.span,
                    });
                    if self.consume(TokenKind::Comma).is_none() {
                        break;
                    }
                }
            }
            self.expect(TokenKind::RightParen, "expected `)`")?;
            self.expect(
                TokenKind::Semicolon,
                "interface requirement must end with `;`; bodies are unavailable",
            )?;
            requirements.push(crate::AstRequirement {
                name: method,
                mutable,
                parameters,
                result,
                span,
            });
        }
        let end = self.expect(TokenKind::RightBrace, "expected `}`")?.span;
        Ok(crate::AstInterface {
            name,
            public,
            requirements,
            span: start.through(end),
        })
    }

    #[allow(clippy::too_many_lines)]
    fn class_decl(&mut self) -> Result<crate::AstClass, Diagnostic> {
        let start = self.current().span;
        let public = if self.current().lexeme == "public" {
            self.advance();
            true
        } else {
            false
        };
        let open = self.current().lexeme == "open";
        if open {
            self.advance();
        }
        if self.current().lexeme != "class" {
            return Err(self.error("E0400", "expected concrete class declaration"));
        }
        self.advance();
        let name = self
            .expect(TokenKind::Identifier, "expected class name")?
            .lexeme;
        let mut relations = Vec::new();
        if self.consume(TokenKind::Colon).is_some() {
            loop {
                relations.push(self.ty()?);
                if self.consume(TokenKind::Comma).is_none() {
                    break;
                }
            }
        }
        self.expect(
            TokenKind::LeftBrace,
            "class requires `{`; generics, implements and extends are unavailable",
        )?;
        let mut fields = Vec::new();
        let mut methods = Vec::new();
        let mut initializer = None;
        while !self.at(TokenKind::RightBrace) && !self.at(TokenKind::Eof) {
            let public = match self.current().lexeme.as_str() {
                "public" => {
                    self.advance();
                    true
                }
                "private" => {
                    self.advance();
                    false
                }
                _ => false,
            };
            let method_open = self.current().lexeme == "open";
            let overriding = self.current().lexeme == "override";
            if method_open || overriding {
                self.advance();
            }
            let mutable = self.consume(TokenKind::KwMut).is_some();
            if self.current().lexeme == "init" {
                if mutable || method_open || overriding || initializer.is_some() {
                    return Err(self.error(
                        "E0400",
                        "one initializer without a mut modifier is permitted",
                    ));
                }
                let token = self.advance();
                // Reuse parameter/block parsing, keeping init's source role explicit.
                let function = self.function_tail(
                    AstType {
                        module: None,
                        name: "int".into(),
                        arguments: Vec::new(),
                        reference: None,
                        span: token.span,
                    },
                    "init".into(),
                    token.span,
                )?;
                initializer = Some(crate::AstClassMethod {
                    open: method_open,
                    overriding,
                    public,
                    mutable: true,
                    function,
                });
            } else {
                let start = self.current().span;
                let ty = self.ty()?;
                let member = self.expect(TokenKind::Identifier, "expected field or method name")?;
                if self.at(TokenKind::LeftParen) {
                    let function = self.function_tail(ty, member.lexeme, start)?;
                    methods.push(crate::AstClassMethod {
                        open: method_open,
                        overriding,
                        public,
                        mutable,
                        function,
                    });
                } else {
                    if mutable || method_open || overriding {
                        return Err(self.error("E0400", "mut is a method receiver modifier"));
                    }
                    let end = self
                        .expect(TokenKind::Semicolon, "expected `;` after class field")?
                        .span;
                    fields.push((
                        public,
                        AstField {
                            ty,
                            name: member.lexeme,
                            span: start.through(end),
                        },
                    ));
                }
            }
        }
        let end = self
            .expect(TokenKind::RightBrace, "expected `}` after class")?
            .span;
        Ok(crate::AstClass {
            open,
            relations,
            name,
            public,
            fields,
            methods,
            initializer,
            span: start.through(end),
        })
    }

    fn enum_decl(&mut self) -> Result<AstEnum, Diagnostic> {
        let start = self.expect(TokenKind::KwEnum, "expected `enum`")?.span;
        let name = self
            .expect(TokenKind::Identifier, "expected enum name")?
            .lexeme;
        let generic_parameters = self.generic_parameters()?;
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
            generic_parameters,
            variants,
            span: start.through(end),
        })
    }

    fn struct_decl(&mut self) -> Result<AstStruct, Diagnostic> {
        let start = self.expect(TokenKind::KwStruct, "expected `struct`")?.span;
        let name = self
            .expect(TokenKind::Identifier, "expected struct name")?
            .lexeme;
        let generic_parameters = self.generic_parameters()?;
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
            generic_parameters,
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
        self.function_tail(return_type, name, start)
    }

    fn function_tail(
        &mut self,
        return_type: AstType,
        name: String,
        start: crate::Span,
    ) -> Result<AstFunction, Diagnostic> {
        let generic_parameters = self.generic_parameters()?;
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
        let base = if name == "init" && self.consume(TokenKind::Colon).is_some() {
            if self.current().lexeme != "base" {
                return Err(self.error("E0421", "initializer must invoke immediate base(...)"));
            }
            self.advance();
            self.expect(TokenKind::LeftParen, "expected base arguments")?;
            let (args, span) = self.arguments()?;
            Some(AstStmt {
                kind: AstStmtKind::Expr(AstExpr {
                    kind: AstExprKind::Call {
                        callee: "$base".into(),
                        type_arguments: Vec::new(),
                        args,
                    },
                    span,
                }),
                span,
            })
        } else {
            None
        };
        let mut body = self.block()?;
        if let Some(base) = base {
            body.statements.insert(0, base);
        }
        Ok(AstFunction {
            return_type,
            name,
            generic_parameters,
            parameters,
            span: start.through(body.span),
            body,
        })
    }

    fn ty(&mut self) -> Result<AstType, Diagnostic> {
        if let Some(reference) = self.consume(TokenKind::KwRef) {
            let mutable = self.consume(TokenKind::KwMut).is_some();
            let pointee = self.ty()?;
            let span = reference.span.through(pointee.span);
            return Ok(AstType {
                module: None,
                name: if mutable { "ref mut" } else { "ref" }.into(),
                arguments: Vec::new(),
                reference: Some(AstReferenceType {
                    pointee: Box::new(pointee),
                    mutable,
                }),
                span,
            });
        }
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
        let arguments = self.type_arguments()?;
        let span = arguments
            .last()
            .map_or(span, |argument| span.through(argument.span));
        Ok(AstType {
            module,
            name,
            arguments,
            reference: None,
            span,
        })
    }

    fn generic_parameters(&mut self) -> Result<Vec<AstGenericParam>, Diagnostic> {
        if self.consume(TokenKind::Less).is_none() {
            return Ok(Vec::new());
        }
        let mut parameters = Vec::new();
        loop {
            let token = self.expect(TokenKind::Identifier, "expected generic parameter")?;
            let mut constraints = Vec::new();
            if self.consume(TokenKind::Colon).is_some() {
                loop {
                    let capability =
                        self.expect(TokenKind::Identifier, "expected capability name after `:`")?;
                    constraints.push(AstCapabilityConstraint {
                        name: capability.lexeme,
                        span: capability.span,
                    });
                    if self.consume(TokenKind::Plus).is_none() {
                        break;
                    }
                }
            }
            parameters.push(AstGenericParam {
                name: token.lexeme,
                constraints,
                span: token.span,
            });
            if self.consume(TokenKind::Comma).is_none() {
                break;
            }
        }
        self.expect(TokenKind::Greater, "expected `>` after generic parameters")?;
        Ok(parameters)
    }

    fn type_arguments(&mut self) -> Result<Vec<AstType>, Diagnostic> {
        if self.consume(TokenKind::Less).is_none() {
            return Ok(Vec::new());
        }
        let mut arguments = Vec::new();
        loop {
            arguments.push(self.ty()?);
            if self.consume(TokenKind::Comma).is_none() {
                break;
            }
        }
        self.expect(TokenKind::Greater, "expected `>` after type arguments")?;
        Ok(arguments)
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
            TokenKind::KwInt | TokenKind::KwBool | TokenKind::KwRef => {
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
            TokenKind::Identifier if self.looks_like_local_declaration() => {
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
            TokenKind::Identifier | TokenKind::Star | TokenKind::LeftParen => {
                let expression = self.expression()?;
                if self.consume(TokenKind::Equal).is_some() {
                    let value = self.expression()?;
                    AstStmtKind::Assign {
                        place: expression,
                        value,
                    }
                } else {
                    AstStmtKind::Expr(expression)
                }
            }
            TokenKind::KwReturn => {
                self.advance();
                AstStmtKind::Return(self.expression()?)
            }
            TokenKind::KwBreak => {
                self.advance();
                AstStmtKind::Break
            }
            TokenKind::KwContinue => {
                self.advance();
                AstStmtKind::Continue
            }
            TokenKind::KwThrow => {
                self.advance();
                AstStmtKind::Throw(if self.at(TokenKind::Semicolon) {
                    None
                } else {
                    Some(self.expression()?)
                })
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
            TokenKind::KwTry => return self.try_statement(start),
            _ => return Err(self.error("E0102", "expected a Vertical-16 statement")),
        };
        let semicolon = self.expect(TokenKind::Semicolon, "expected `;` after statement")?;
        Ok(AstStmt {
            kind,
            span: start.through(semicolon.span),
        })
    }

    fn try_statement(&mut self, start: crate::Span) -> Result<AstStmt, Diagnostic> {
        self.expect(TokenKind::KwTry, "expected `try`")?;
        let body = self.block()?;
        let mut catches = Vec::new();
        while self.consume(TokenKind::KwCatch).is_some() {
            let catch_start = self.tokens[self.cursor - 1].span;
            self.expect(TokenKind::LeftParen, "expected `(` after `catch`")?;
            let ty = self.ty()?;
            let name = self
                .expect(TokenKind::Identifier, "expected catch binding")?
                .lexeme;
            self.expect(TokenKind::RightParen, "expected `)` after catch binding")?;
            let handler = self.block()?;
            catches.push(AstCatch {
                ty,
                name,
                span: catch_start.through(handler.span),
                body: handler,
            });
        }
        let finally = if self.consume(TokenKind::KwFinally).is_some() {
            Some(self.block()?)
        } else {
            None
        };
        if catches.is_empty() && finally.is_none() {
            return Err(Diagnostic::new(
                "E0430",
                Phase::Parse,
                DiagnosticCategory::Syntax,
                "try requires at least one typed catch or a finally block",
                Some(body.span),
            ));
        }
        let end = finally
            .as_ref()
            .map(|block| block.span)
            .or_else(|| catches.last().map(|catch| catch.span))
            .expect("try has a catch or finally");
        Ok(AstStmt {
            span: start.through(end),
            kind: AstStmtKind::Try {
                body,
                catches,
                finally,
            },
        })
    }

    fn match_statement(&mut self, start: crate::Span) -> Result<AstStmt, Diagnostic> {
        self.expect(TokenKind::KwMatch, "expected `match`")?;
        self.expect(TokenKind::LeftParen, "expected `(` after `match`")?;
        let mode = if self.consume(TokenKind::KwRef).is_some() {
            if self.consume(TokenKind::KwMut).is_some() {
                AstMatchMode::MutableRef
            } else {
                AstMatchMode::SharedRef
            }
        } else {
            AstMatchMode::Value
        };
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
            kind: AstStmtKind::Match {
                mode,
                scrutinee,
                arms,
            },
            span: start.through(right),
        })
    }

    fn variant_pattern(&mut self) -> Result<AstVariantPattern, Diagnostic> {
        let first = self.expect(TokenKind::Identifier, "expected enum name in pattern")?;
        let first_arguments = self.type_arguments()?;
        self.expect(TokenKind::Dot, "variant patterns must be qualified")?;
        let second = self.expect(TokenKind::Identifier, "expected variant name after `.`")?;
        let second_arguments = self.type_arguments()?;
        let (module, enum_name, type_arguments, variant, mut end) =
            if self.consume(TokenKind::Dot).is_some() {
                let third =
                    self.expect(TokenKind::Identifier, "expected variant name after `.`")?;
                (
                    Some(first.lexeme),
                    second.lexeme,
                    second_arguments,
                    third.lexeme,
                    third.span,
                )
            } else {
                (
                    None,
                    first.lexeme,
                    first_arguments,
                    second.lexeme,
                    second.span,
                )
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
            type_arguments,
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
        } else if let Some(star) = self.consume(TokenKind::Star) {
            let operand = self.unary()?;
            let span = star.span.through(operand.span);
            Ok(AstExpr {
                kind: AstExprKind::Unary {
                    op: AstUnaryOp::Dereference,
                    operand: Box::new(operand),
                },
                span,
            })
        } else if let Some(reference) = self.consume(TokenKind::Ampersand) {
            let mutable = self.consume(TokenKind::KwMut).is_some();
            let operand = self.unary()?;
            let span = reference.span.through(operand.span);
            Ok(AstExpr {
                kind: AstExprKind::Unary {
                    op: if mutable {
                        AstUnaryOp::BorrowMutable
                    } else {
                        AstUnaryOp::BorrowShared
                    },
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
            TokenKind::LeftBracket => {
                let mut rows = Vec::new();
                if !self.at(TokenKind::RightBracket) {
                    loop {
                        let mut row = vec![self.expression()?];
                        while self.consume(TokenKind::Comma).is_some() {
                            if self.at(TokenKind::RightBracket) {
                                break;
                            }
                            row.push(self.expression()?);
                        }
                        rows.push(row);
                        if self.consume(TokenKind::Semicolon).is_none() {
                            break;
                        }
                        // A separator always requires a nonempty next row.
                        if self.at(TokenKind::RightBracket) {
                            return Err(Diagnostic::new(
                                "E0330",
                                Phase::Parse,
                                DiagnosticCategory::Syntax,
                                "trailing matrix row separator is not permitted",
                                Some(self.current().span),
                            ));
                        }
                    }
                }
                let right = self.expect(
                    TokenKind::RightBracket,
                    "expected `]` after mathematical literal",
                )?;
                AstExpr {
                    kind: AstExprKind::MathematicalLiteral { rows },
                    span: token.span.through(right.span),
                }
            }
            TokenKind::LeftBrace => {
                let mut elements = Vec::new();
                if !self.at(TokenKind::RightBrace) {
                    loop {
                        elements.push(self.expression()?);
                        if self.consume(TokenKind::Comma).is_none() {
                            break;
                        }
                        if self.at(TokenKind::RightBrace) {
                            break;
                        }
                    }
                }
                let right = self.expect(
                    TokenKind::RightBrace,
                    "expected `}` after collection literal",
                )?;
                AstExpr {
                    kind: AstExprKind::CollectionLiteral(elements),
                    span: token.span.through(right.span),
                }
            }
            TokenKind::Identifier | TokenKind::KwInt | TokenKind::KwBool => {
                self.identifier_primary(token)?
            }
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
        loop {
            if self.consume(TokenKind::Dot).is_some() {
                let member = self.expect(TokenKind::Identifier, "expected field name after `.`")?;
                if self.consume(TokenKind::LeftParen).is_some() {
                    let (args, end) = self.arguments()?;
                    let span = expr.span.through(end);
                    expr = AstExpr {
                        kind: AstExprKind::MethodCall {
                            receiver: Box::new(expr),
                            method: member.lexeme,
                            args,
                        },
                        span,
                    };
                    continue;
                }
                let span = expr.span.through(member.span);
                expr = AstExpr {
                    kind: AstExprKind::Field {
                        base: Box::new(expr),
                        name: member.lexeme,
                        name_span: member.span,
                    },
                    span,
                };
            } else if self.consume(TokenKind::LeftBracket).is_some() {
                let mut indices = vec![self.expression()?];
                while self.consume(TokenKind::Comma).is_some() {
                    indices.push(self.expression()?);
                }
                let right = self.expect(TokenKind::RightBracket, "expected `]` after index")?;
                let span = expr.span.through(right.span);
                expr = AstExpr {
                    kind: AstExprKind::Index {
                        base: Box::new(expr),
                        indices,
                    },
                    span,
                };
            } else {
                break;
            }
        }
        Ok(expr)
    }

    #[allow(clippy::too_many_lines)]
    fn identifier_primary(&mut self, token: Token) -> Result<AstExpr, Diagnostic> {
        let first_arguments = if self.generic_suffix_before_apply() {
            self.type_arguments()?
        } else {
            Vec::new()
        };
        if self.consume(TokenKind::Dot).is_some() {
            let member = self.expect(TokenKind::Identifier, "expected member name after `.`")?;
            let member_arguments = self.type_arguments()?;
            if self.consume(TokenKind::Dot).is_some() {
                if !first_arguments.is_empty() {
                    return Err(self.error("E0103", "module qualifiers cannot have type arguments"));
                }
                let variant =
                    self.expect(TokenKind::Identifier, "expected variant name after `.`")?;
                let (args, parenthesized, end) = if self.consume(TokenKind::LeftParen).is_some() {
                    let (args, right) = self.arguments()?;
                    (args, true, right)
                } else {
                    (Vec::new(), false, variant.span)
                };
                if !parenthesized && member_arguments.is_empty() {
                    let inner_span = token.span.through(member.span);
                    return Ok(AstExpr {
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
                        span: token.span.through(end),
                    });
                }
                return Ok(AstExpr {
                    kind: AstExprKind::VariantCall {
                        module: token.lexeme,
                        enum_name: member.lexeme,
                        type_arguments: member_arguments,
                        variant: variant.lexeme,
                        args,
                        parenthesized,
                    },
                    span: token.span.through(end),
                });
            }
            if !first_arguments.is_empty() || self.at(TokenKind::LeftParen) {
                let (args, parenthesized, end) = if self.consume(TokenKind::LeftParen).is_some() {
                    let (args, right) = self.arguments()?;
                    (args, true, right)
                } else {
                    (Vec::new(), false, member.span)
                };
                return Ok(AstExpr {
                    kind: AstExprKind::QualifiedCall {
                        module: token.lexeme,
                        function: member.lexeme,
                        type_arguments: if first_arguments.is_empty() {
                            member_arguments
                        } else {
                            first_arguments
                        },
                        args,
                        parenthesized,
                    },
                    span: token.span.through(end),
                });
            }
            if !member_arguments.is_empty() {
                return Err(self.error("E0103", "generic module member must be applied"));
            }
            return Ok(AstExpr {
                kind: AstExprKind::Field {
                    base: Box::new(AstExpr {
                        kind: AstExprKind::Name(token.lexeme),
                        span: token.span,
                    }),
                    name: member.lexeme,
                    name_span: member.span,
                },
                span: token.span.through(member.span),
            });
        }
        if self.consume(TokenKind::LeftParen).is_some() {
            let (args, right) = self.arguments()?;
            return Ok(AstExpr {
                kind: AstExprKind::Call {
                    callee: token.lexeme,
                    type_arguments: first_arguments,
                    args,
                },
                span: token.span.through(right),
            });
        }
        if !first_arguments.is_empty() {
            return Err(self.error("E0103", "generic application requires construction or call"));
        }
        Ok(AstExpr {
            kind: AstExprKind::Name(token.lexeme),
            span: token.span,
        })
    }

    fn generic_suffix_before_apply(&self) -> bool {
        if !self.at(TokenKind::Less) {
            return false;
        }
        let mut depth = 0_u32;
        let mut index = self.cursor;
        while let Some(token) = self.tokens.get(index) {
            match token.kind {
                TokenKind::Less => depth += 1,
                TokenKind::Greater => {
                    depth -= 1;
                    if depth == 0 {
                        return matches!(
                            self.tokens.get(index + 1).map(|token| token.kind),
                            Some(TokenKind::LeftParen | TokenKind::Dot)
                        );
                    }
                }
                TokenKind::Semicolon | TokenKind::Eof if depth > 0 => return false,
                _ => {}
            }
            index += 1;
        }
        false
    }

    fn looks_like_local_declaration(&self) -> bool {
        fn skip_type(tokens: &[Token], mut index: usize) -> Option<usize> {
            if tokens.get(index)?.kind == TokenKind::KwRef {
                index += 1;
                if tokens
                    .get(index)
                    .is_some_and(|token| token.kind == TokenKind::KwMut)
                {
                    index += 1;
                }
                return skip_type(tokens, index);
            }
            if !matches!(
                tokens.get(index)?.kind,
                TokenKind::Identifier | TokenKind::KwInt | TokenKind::KwBool
            ) {
                return None;
            }
            index += 1;
            if tokens
                .get(index)
                .is_some_and(|token| token.kind == TokenKind::Dot)
            {
                index += 1;
                if tokens.get(index)?.kind != TokenKind::Identifier {
                    return None;
                }
                index += 1;
            }
            if tokens
                .get(index)
                .is_some_and(|token| token.kind == TokenKind::Less)
            {
                index += 1;
                loop {
                    index = skip_type(tokens, index)?;
                    match tokens.get(index)?.kind {
                        TokenKind::Comma => index += 1,
                        TokenKind::Greater => {
                            index += 1;
                            break;
                        }
                        _ => return None,
                    }
                }
            }
            Some(index)
        }
        let Some(after_type) = skip_type(&self.tokens, self.cursor) else {
            return false;
        };
        self.tokens
            .get(after_type)
            .is_some_and(|token| token.kind == TokenKind::Identifier)
            && self
                .tokens
                .get(after_type + 1)
                .is_some_and(|token| token.kind == TokenKind::Equal)
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
