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
    /// `import`.
    KwImport,
    /// `alias`.
    KwAlias,
    /// `(`.
    LeftParen,
    /// `)`.
    RightParen,
    /// `{`.
    LeftBrace,
    /// `}`.
    RightBrace,
    /// `;`.
    Semicolon,
    /// `,`.
    Comma,
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
    /// `=`.
    Equal,
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
        let start = cursor;
        match bytes[cursor] {
            b' ' | b'\t' | b'\r' | b'\n' => cursor += 1,
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
                    "import" => TokenKind::KwImport,
                    "alias" => TokenKind::KwAlias,
                    _ => TokenKind::Identifier,
                };
                push(&mut tokens, kind, source, start, cursor);
            }
            b'(' => single(&mut tokens, TokenKind::LeftParen, source, &mut cursor),
            b')' => single(&mut tokens, TokenKind::RightParen, source, &mut cursor),
            b'{' => single(&mut tokens, TokenKind::LeftBrace, source, &mut cursor),
            b'}' => single(&mut tokens, TokenKind::RightBrace, source, &mut cursor),
            b';' => single(&mut tokens, TokenKind::Semicolon, source, &mut cursor),
            b',' => single(&mut tokens, TokenKind::Comma, source, &mut cursor),
            b'.' => single(&mut tokens, TokenKind::Dot, source, &mut cursor),
            b'+' => single(&mut tokens, TokenKind::Plus, source, &mut cursor),
            b'-' => single(&mut tokens, TokenKind::Minus, source, &mut cursor),
            b'*' => single(&mut tokens, TokenKind::Star, source, &mut cursor),
            b'/' => single(&mut tokens, TokenKind::Slash, source, &mut cursor),
            b'%' => single(&mut tokens, TokenKind::Percent, source, &mut cursor),
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
}
