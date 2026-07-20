//! Source locations attached to selected IR instructions.

/// A one-based source location with an optional source path.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct IRSourceLocation {
    /// One-based source line.
    pub line: i64,
    /// One-based source column.
    pub column: i64,
    /// Optional path of the source file.
    pub path: Option<String>,
}
