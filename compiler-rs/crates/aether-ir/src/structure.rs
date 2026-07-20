//! Nominal struct definitions retained by an IR module.

use crate::IRType;

/// A nominal struct layout with fields in declaration order.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct IRStructDefinition {
    /// Struct name.
    pub name: String,
    /// Ordered `(field name, field type)` pairs.
    pub fields: Vec<(String, IRType)>,
}
