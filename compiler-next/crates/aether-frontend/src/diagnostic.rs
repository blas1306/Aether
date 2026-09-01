//! Structured diagnostics and source coordinates.

use std::fmt;

/// Session-local source identity. Paths are provenance, not semantic identity.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct SourceId(pub u32);

/// Half-open byte range in one unambiguously identified source.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct Span {
    /// Source containing this range.
    pub source: SourceId,
    /// Inclusive byte offset.
    pub start: usize,
    /// Exclusive byte offset.
    pub end: usize,
}

impl Span {
    /// Creates a half-open span.
    #[must_use]
    pub const fn new(start: usize, end: usize) -> Self {
        Self::in_source(SourceId(0), start, end)
    }

    /// Creates a half-open span in an explicit source.
    #[must_use]
    pub const fn in_source(source: SourceId, start: usize, end: usize) -> Self {
        Self { source, start, end }
    }

    /// Covers both spans.
    #[must_use]
    pub fn through(self, other: Self) -> Self {
        debug_assert_eq!(self.source, other.source);
        Self::in_source(
            self.source,
            self.start.min(other.start),
            self.end.max(other.end),
        )
    }
}

/// Compiler phase that produced a diagnostic.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Phase {
    /// Tokenization.
    Lex,
    /// Syntactic analysis.
    Parse,
    /// Resolution and typing.
    Semantic,
    /// Flow MIR construction or verification.
    Mir,
    /// SSA construction or verification.
    Ssa,
    /// LLVM emission.
    Backend,
    /// Native toolchain invocation.
    Toolchain,
    /// Driver and input handling.
    Driver,
}

impl fmt::Display for Phase {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", format!("{self:?}").to_ascii_lowercase())
    }
}

/// Stable broad classification.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DiagnosticCategory {
    /// Invalid source syntax.
    Syntax,
    /// An intentionally unadmitted feature.
    Unsupported,
    /// Name resolution failure.
    Name,
    /// Static type failure.
    Type,
    /// Compile-time integer range or overflow failure.
    Integer,
    /// Internal IR invariant rejection.
    Verification,
    /// Host toolchain failure.
    Toolchain,
    /// Source/input/output failure.
    Io,
}

/// A compiler error record independent from rendering.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Diagnostic {
    /// Stable identifier.
    pub code: &'static str,
    /// Producing phase.
    pub phase: Phase,
    /// Broad category.
    pub category: DiagnosticCategory,
    /// Human-readable explanation.
    pub message: String,
    /// Primary source location, when available.
    pub span: Option<Span>,
    /// Source display name retained when a diagnostic leaves its compilation session.
    pub source_name: Option<String>,
}

impl Diagnostic {
    /// Creates a source diagnostic.
    #[must_use]
    pub fn new(
        code: &'static str,
        phase: Phase,
        category: DiagnosticCategory,
        message: impl Into<String>,
        span: Option<Span>,
    ) -> Self {
        Self {
            code,
            phase,
            category,
            message: message.into(),
            span,
            source_name: None,
        }
    }

    /// Attaches source provenance without changing the structured location.
    #[must_use]
    pub fn with_source_name(mut self, source_name: impl Into<String>) -> Self {
        self.source_name = Some(source_name.into());
        self
    }

    /// Renders deterministically with a one-line location.
    #[must_use]
    pub fn render(&self, source: Option<&SourceFile>) -> String {
        let matching_source = source.filter(|file| {
            self.span.is_none_or(|span| span.source == file.id)
                && self
                    .source_name
                    .as_ref()
                    .is_none_or(|name| name == &file.name)
        });
        let location = self
            .span
            .and_then(|span| matching_source.map(|file| file.line_column(span.start)));
        match (matching_source, location) {
            (Some(file), Some((line, column))) => format!(
                "{}:{}:{}: error[{}] ({}): {}",
                file.name, line, column, self.code, self.phase, self.message
            ),
            _ => self.source_name.as_ref().map_or_else(
                || format!("error[{}] ({}): {}", self.code, self.phase, self.message),
                |name| {
                    format!(
                        "{name}: error[{}] ({}): {}",
                        self.code, self.phase, self.message
                    )
                },
            ),
        }
    }
}

/// Owned source input for a compilation session.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct SourceFile {
    /// Session-local provenance identity.
    pub id: SourceId,
    /// Logical display name, not a semantic absolute identity.
    pub name: String,
    /// UTF-8 source text.
    pub text: String,
}

impl SourceFile {
    /// Creates a source record.
    #[must_use]
    pub fn new(name: impl Into<String>, text: impl Into<String>) -> Self {
        Self::with_id(SourceId(0), name, text)
    }

    /// Creates a source record with an explicit session-local identity.
    #[must_use]
    pub fn with_id(id: SourceId, name: impl Into<String>, text: impl Into<String>) -> Self {
        Self {
            id,
            name: name.into(),
            text: text.into(),
        }
    }

    /// Returns one-based line and column for a byte offset.
    #[must_use]
    pub fn line_column(&self, offset: usize) -> (usize, usize) {
        let prefix = &self.text[..offset.min(self.text.len())];
        let line = prefix.bytes().filter(|byte| *byte == b'\n').count() + 1;
        let column = prefix
            .rsplit_once('\n')
            .map_or(prefix.chars().count() + 1, |(_, tail)| {
                tail.chars().count() + 1
            });
        (line, column)
    }
}
