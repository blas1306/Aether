//! Small, fail-closed lexer for the scalar language slices.

use crate::{Diagnostic, DiagnosticCategory, Phase, SourceFile, Span};

/// Token kinds. Payload text is retained in [`Token::lexeme`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TokenKind {
    /// Identifier.
    Identifier,
    /// Unsuffixed decimal integer literal.
    Integer,
    /// Unsuffixed decimal floating literal.
    Float,
    /// Immutable UTF-8 string literal. The lexeme retains the exact spelling.
    String,
    /// `int`.
    KwInt,
    /// `bool`.
    KwBool,
    /// `true`.
    KwTrue,
    /// `false`.
    KwFalse,
    /// `if`.
    KwIf,
    /// `else`.
    KwElse,
    /// `while`.
    KwWhile,
    /// `return`.
    KwReturn,
    /// `throw`.
    KwThrow,
    /// `try`.
    KwTry,
    /// `catch`.
    KwCatch,
    /// `finally`.
    KwFinally,
    /// `break`.
    KwBreak,
    /// `continue`.
    KwContinue,
    /// `import`.
    KwImport,
    /// `alias`.
    KwAlias,
    /// `struct`.
    KwStruct,
    /// `enum`.
    KwEnum,
    /// `match`.
    KwMatch,
    /// `ref`.
    KwRef,
    /// `mut`.
    KwMut,
    /// `(`.
    LeftParen,
    /// `)`.
    RightParen,
    /// `{`.
    LeftBrace,
    /// `}`.
    RightBrace,
    /// `[`.
    LeftBracket,
    /// `]`.
    RightBracket,
    /// `;`.
    Semicolon,
    /// `,`.
    Comma,
    /// `:`.
    Colon,
    /// `.`.
    Dot,
    /// `+`.
    Plus,
    /// `-`.
    Minus,
    /// `*`.
    Star,
    /// `/`.
    Slash,
    /// `%`.
    Percent,
    /// `&`.
    Ampersand,
    /// `=`.
    Equal,
    /// `=>`.
    FatArrow,
    /// `==`.
    EqualEqual,
    /// `!=`.
    BangEqual,
    /// `<`.
    Less,
    /// `<=`.
    LessEqual,
    /// `>`.
    Greater,
    /// `>=`.
    GreaterEqual,
    /// End marker.
    Eof,
}

/// One source token.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Token {
    /// Kind.
    pub kind: TokenKind,
    /// Exact source spelling.
    pub lexeme: String,
    /// Source bytes.
    pub span: Span,
}

/// Tokenizes a UTF-8 source file.
#[allow(clippy::too_many_lines)]
pub fn lex(source: &SourceFile) -> Result<Vec<Token>, Vec<Diagnostic>> {
    let bytes = source.text.as_bytes();
    let mut tokens = Vec::new();
    let mut diagnostics = Vec::new();
    let mut cursor = 0;
    while cursor < bytes.len() {
        if let Err(diagnostic) = skip_trivia(source, &mut cursor) {
            diagnostics.push(diagnostic);
            break;
        }
        if cursor == bytes.len() {
            break;
        }
        let start = cursor;
        match bytes[cursor] {
            b'0'..=b'9' => {
                cursor += 1;
                while cursor < bytes.len() && bytes[cursor].is_ascii_digit() {
                    cursor += 1;
                }
                let mut kind = TokenKind::Integer;
                if bytes.get(cursor) == Some(&b'.')
                    && bytes.get(cursor + 1).is_some_and(u8::is_ascii_digit)
                {
                    kind = TokenKind::Float;
                    cursor += 1;
                    while cursor < bytes.len() && bytes[cursor].is_ascii_digit() {
                        cursor += 1;
                    }
                }
                if matches!(bytes.get(cursor), Some(b'e' | b'E')) {
                    kind = TokenKind::Float;
                    cursor += 1;
                    if matches!(bytes.get(cursor), Some(b'+' | b'-')) {
                        cursor += 1;
                    }
                    let exponent_start = cursor;
                    while cursor < bytes.len() && bytes[cursor].is_ascii_digit() {
                        cursor += 1;
                    }
                    if cursor == exponent_start {
                        diagnostics.push(Diagnostic::new(
                            "E0001",
                            Phase::Lex,
                            DiagnosticCategory::Syntax,
                            "floating exponent requires digits",
                            Some(Span::in_source(source.id, start, cursor)),
                        ));
                    }
                }
                push(&mut tokens, kind, source, start, cursor);
            }
            b'"' => {
                cursor += 1;
                let mut terminated = false;
                while cursor < bytes.len() {
                    match bytes[cursor] {
                        b'"' => {
                            cursor += 1;
                            terminated = true;
                            break;
                        }
                        b'\\' => {
                            cursor += 1;
                            match bytes.get(cursor) {
                                Some(b'0' | b'n' | b'r' | b't' | b'"' | b'\\') => cursor += 1,
                                Some(_) => {
                                    let end = (cursor + 1).min(bytes.len());
                                    diagnostics.push(Diagnostic::new(
                                        "E0003",
                                        Phase::Lex,
                                        DiagnosticCategory::Syntax,
                                        "unsupported string escape",
                                        Some(Span::in_source(source.id, cursor - 1, end)),
                                    ));
                                    cursor = end;
                                }
                                None => break,
                            }
                        }
                        b'\n' | b'\r' => break,
                        byte => {
                            cursor += if byte.is_ascii() {
                                1
                            } else {
                                source.text[cursor..]
                                    .chars()
                                    .next()
                                    .map_or(1, char::len_utf8)
                            };
                        }
                    }
                }
                if terminated {
                    push(&mut tokens, TokenKind::String, source, start, cursor);
                } else {
                    diagnostics.push(Diagnostic::new(
                        "E0003",
                        Phase::Lex,
                        DiagnosticCategory::Syntax,
                        "unterminated string literal",
                        Some(Span::in_source(source.id, start, cursor)),
                    ));
                }
            }
            b'a'..=b'z' | b'A'..=b'Z' | b'_' => {
                cursor += 1;
                while cursor < bytes.len()
                    && (bytes[cursor].is_ascii_alphanumeric() || bytes[cursor] == b'_')
                {
                    cursor += 1;
                }
                let text = &source.text[start..cursor];
                let kind = match text {
                    "int" => TokenKind::KwInt,
                    "bool" => TokenKind::KwBool,
                    "true" => TokenKind::KwTrue,
                    "false" => TokenKind::KwFalse,
                    "if" => TokenKind::KwIf,
                    "else" => TokenKind::KwElse,
                    "while" => TokenKind::KwWhile,
                    "return" => TokenKind::KwReturn,
                    "throw" => TokenKind::KwThrow,
                    "try" => TokenKind::KwTry,
                    "catch" => TokenKind::KwCatch,
                    "finally" => TokenKind::KwFinally,
                    "break" => TokenKind::KwBreak,
                    "continue" => TokenKind::KwContinue,
                    "import" => TokenKind::KwImport,
                    "alias" => TokenKind::KwAlias,
                    "struct" => TokenKind::KwStruct,
                    "enum" => TokenKind::KwEnum,
                    "match" => TokenKind::KwMatch,
                    "ref" => TokenKind::KwRef,
                    "mut" => TokenKind::KwMut,
                    _ => TokenKind::Identifier,
                };
                push(&mut tokens, kind, source, start, cursor);
            }
            b'(' => single(&mut tokens, TokenKind::LeftParen, source, &mut cursor),
            b')' => single(&mut tokens, TokenKind::RightParen, source, &mut cursor),
            b'{' => single(&mut tokens, TokenKind::LeftBrace, source, &mut cursor),
            b'}' => single(&mut tokens, TokenKind::RightBrace, source, &mut cursor),
            b'[' => single(&mut tokens, TokenKind::LeftBracket, source, &mut cursor),
            b']' => single(&mut tokens, TokenKind::RightBracket, source, &mut cursor),
            b';' => single(&mut tokens, TokenKind::Semicolon, source, &mut cursor),
            b',' => single(&mut tokens, TokenKind::Comma, source, &mut cursor),
            b':' => single(&mut tokens, TokenKind::Colon, source, &mut cursor),
            b'.' => single(&mut tokens, TokenKind::Dot, source, &mut cursor),
            b'+' => single(&mut tokens, TokenKind::Plus, source, &mut cursor),
            b'-' => single(&mut tokens, TokenKind::Minus, source, &mut cursor),
            b'*' => single(&mut tokens, TokenKind::Star, source, &mut cursor),
            b'/' => single(&mut tokens, TokenKind::Slash, source, &mut cursor),
            b'%' => single(&mut tokens, TokenKind::Percent, source, &mut cursor),
            b'&' => single(&mut tokens, TokenKind::Ampersand, source, &mut cursor),
            b'=' if bytes.get(cursor + 1) == Some(&b'>') => {
                cursor += 2;
                push(&mut tokens, TokenKind::FatArrow, source, start, cursor);
            }
            b'=' => double_or_single(
                &mut tokens,
                source,
                &mut cursor,
                TokenKind::Equal,
                TokenKind::EqualEqual,
            ),
            b'<' => double_or_single(
                &mut tokens,
                source,
                &mut cursor,
                TokenKind::Less,
                TokenKind::LessEqual,
            ),
            b'>' => double_or_single(
                &mut tokens,
                source,
                &mut cursor,
                TokenKind::Greater,
                TokenKind::GreaterEqual,
            ),
            b'!' if bytes.get(cursor + 1) == Some(&b'=') => {
                cursor += 2;
                push(&mut tokens, TokenKind::BangEqual, source, start, cursor);
            }
            byte => {
                let len = if byte.is_ascii() {
                    1
                } else {
                    source.text[start..]
                        .chars()
                        .next()
                        .map_or(1, char::len_utf8)
                };
                cursor += len;
                diagnostics.push(Diagnostic::new(
                    "E0001",
                    Phase::Lex,
                    DiagnosticCategory::Syntax,
                    format!("unexpected character `{}`", &source.text[start..cursor]),
                    Some(Span::in_source(source.id, start, cursor)),
                ));
            }
        }
    }
    tokens.push(Token {
        kind: TokenKind::Eof,
        lexeme: String::new(),
        span: Span::in_source(source.id, cursor, cursor),
    });
    if diagnostics.is_empty() {
        Ok(tokens)
    } else {
        Err(diagnostics)
    }
}

/// Skip trivia directly in the original byte buffer. Coordinates continue to
/// come from `SourceFile`; no rewritten source or parser-visible trivia is used.
fn skip_trivia(source: &SourceFile, cursor: &mut usize) -> Result<(), Diagnostic> {
    let bytes = source.text.as_bytes();
    loop {
        match bytes.get(*cursor) {
            Some(b' ' | b'\t' | b'\r' | b'\n') => *cursor += 1,
            Some(b'/') if bytes.get(*cursor + 1) == Some(&b'/') => {
                *cursor += 2;
                while bytes
                    .get(*cursor)
                    .is_some_and(|b| !matches!(b, b'\r' | b'\n'))
                {
                    *cursor += 1;
                }
            }
            Some(b'/') if bytes.get(*cursor + 1) == Some(&b'*') => {
                let start = *cursor;
                *cursor += 2;
                // Non-nesting: only the first closing delimiter has meaning.
                while *cursor < bytes.len()
                    && !(bytes[*cursor] == b'*' && bytes.get(*cursor + 1) == Some(&b'/'))
                {
                    *cursor += 1;
                }
                if *cursor == bytes.len() {
                    return Err(Diagnostic::new(
                        "E0002",
                        Phase::Lex,
                        DiagnosticCategory::Syntax,
                        "unterminated block comment",
                        Some(Span::in_source(source.id, start, start + 2)),
                    ));
                }
                *cursor += 2;
            }
            _ => return Ok(()),
        }
    }
}

fn push(tokens: &mut Vec<Token>, kind: TokenKind, source: &SourceFile, start: usize, end: usize) {
    tokens.push(Token {
        kind,
        lexeme: source.text[start..end].to_owned(),
        span: Span::in_source(source.id, start, end),
    });
}

fn single(tokens: &mut Vec<Token>, kind: TokenKind, source: &SourceFile, cursor: &mut usize) {
    let start = *cursor;
    *cursor += 1;
    push(tokens, kind, source, start, *cursor);
}

fn double_or_single(
    tokens: &mut Vec<Token>,
    source: &SourceFile,
    cursor: &mut usize,
    single_kind: TokenKind,
    double_kind: TokenKind,
) {
    let start = *cursor;
    *cursor += 1;
    let kind = if source.text.as_bytes().get(*cursor) == Some(&b'=') {
        *cursor += 1;
        double_kind
    } else {
        single_kind
    };
    push(tokens, kind, source, start, *cursor);
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn preserves_byte_spans() {
        let source = SourceFile::new("span.ae", "int main() { return 42; }");
        let tokens = lex(&source).unwrap();
        assert_eq!(tokens[0].span, Span::new(0, 3));
        assert_eq!(tokens[5].lexeme, "return");
        assert_eq!(&source.text[tokens[6].span.start..tokens[6].span.end], "42");
    }

    #[test]
    fn division_and_remainder_are_tokens() {
        let tokens = lex(&SourceFile::new("ops.ae", "int main(){return 4/2%1;}")).unwrap();
        assert!(tokens.iter().any(|token| token.kind == TokenKind::Slash));
        assert!(tokens.iter().any(|token| token.kind == TokenKind::Percent));
    }

    #[test]
    fn comments_are_whitespace_with_physical_spans() {
        for newline in ["\n", "\r\n"] {
            let text = format!(
                "// whole line{newline}int /* type */ x = 1; // trailing{newline}\
                 /* λ{newline}int main() {{ return 7; }} // \"string\" + - * /{newline}*/\
                 x/*between*/+1; x// adjacent{newline}+1; // EOF"
            );
            let source = SourceFile::with_id(crate::SourceId(7), "comments.ae", text);
            let tokens = lex(&source).unwrap();
            let plain = lex(&SourceFile::new("plain.ae", "int x = 1; x+1; x+1;")).unwrap();
            assert_eq!(
                tokens
                    .iter()
                    .map(|t| (t.kind, &t.lexeme))
                    .collect::<Vec<_>>(),
                plain
                    .iter()
                    .map(|t| (t.kind, &t.lexeme))
                    .collect::<Vec<_>>()
            );
            for token in &tokens {
                assert_eq!(token.span.source, source.id);
                assert_eq!(&source.text[token.span.start..token.span.end], token.lexeme);
            }
            assert_eq!(source.line_column(tokens[5].span.start), (5, 3));
            assert_eq!(tokens.last().unwrap().span.start, source.text.len());
        }
    }

    #[test]
    fn comments_do_not_merge_operators_or_nest() {
        use TokenKind::{Equal, Greater, Identifier, Less};

        let source = SourceFile::new(
            "operators.ae",
            "a / b * c <= d >= e == f != g => h & i < /*gap*/ = >/**/= =/**/= !/**/=",
        );
        // `!` alone remains invalid, even with a following separated `=`.
        let error = lex(&source).unwrap_err();
        assert_eq!(error.len(), 1);
        assert_eq!(error[0].message, "unexpected character `!`");
        let valid = SourceFile::new("operators.ae", source.text.replace("!/**/=", ""));
        let kinds = lex(&valid)
            .unwrap()
            .iter()
            .map(|t| t.kind)
            .collect::<Vec<_>>();
        assert_eq!(
            kinds,
            vec![
                Identifier,
                TokenKind::Slash,
                Identifier,
                TokenKind::Star,
                Identifier,
                TokenKind::LessEqual,
                Identifier,
                TokenKind::GreaterEqual,
                Identifier,
                TokenKind::EqualEqual,
                Identifier,
                TokenKind::BangEqual,
                Identifier,
                TokenKind::FatArrow,
                Identifier,
                TokenKind::Ampersand,
                Identifier,
                Less,
                Equal,
                Greater,
                Equal,
                Equal,
                Equal,
                TokenKind::Eof,
            ]
        );
        let tokens = lex(&SourceFile::new("nest.ae", "/* outer /* inner */ tail */")).unwrap();
        assert_eq!(
            tokens.iter().map(|t| t.lexeme.as_str()).collect::<Vec<_>>(),
            ["tail", "*", "/", ""]
        );
    }

    #[test]
    fn unterminated_block_comment_points_to_opening() {
        for text in ["/*", "/* never closed", "/* λ\n*", "/* outer /* inner"] {
            let source =
                SourceFile::with_id(crate::SourceId(3), "open.ae", format!(" \r\n  {text}"));
            let errors = lex(&source).unwrap_err();
            assert_eq!(errors.len(), 1);
            let error = &errors[0];
            assert_eq!(error.code, "E0002");
            assert_eq!(error.phase, Phase::Lex);
            assert_eq!(error.category, DiagnosticCategory::Syntax);
            assert_eq!(error.span, Some(Span::in_source(source.id, 5, 7)));
            assert_eq!(
                error.render(Some(&source)),
                "open.ae:2:3: error[E0002] (lex): unterminated block comment"
            );
        }
    }

    #[test]
    fn diagnostic_after_multiline_comment_has_exact_position() {
        for newline in ["\n", "\r\n"] {
            let source = SourceFile::new(
                "position.ae",
                format!("/*{newline}line 2{newline}line 3{newline}*/{newline}@"),
            );
            let error = &lex(&source).unwrap_err()[0];
            assert_eq!(
                error.span,
                Some(Span::new(source.text.len() - 1, source.text.len()))
            );
            assert_eq!(source.line_column(error.span.unwrap().start), (5, 1));
            assert_eq!(
                error.render(Some(&source)),
                "position.ae:5:1: error[E0001] (lex): unexpected character `@`"
            );
            let unicode = SourceFile::new("unicode.ae", "/*λ*/ @");
            assert_eq!(
                unicode.line_column(lex(&unicode).unwrap_err()[0].span.unwrap().start),
                (1, 7)
            );
        }
    }
}
