//! Constant payloads represented by `IRConst`.

/// Nominal enum constant retained until code generation.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct IREnumConstant {
    /// Canonical enum name.
    pub enum_name: String,
    /// Declared member name.
    pub member_name: String,
    /// Zero-based member identifier.
    pub member_id: i32,
    /// Runtime discriminant.
    pub discriminant: i32,
}

/// A scalar or nominal constant payload.
#[derive(Clone, Debug, PartialEq)]
pub enum IRConstant {
    /// The contextual absent value of a nullable result type.
    Null,
    /// A boolean constant.
    Bool(bool),
    /// A signed 32-bit integer constant.
    Int(i32),
    /// A floating-point constant used by `float` and `double` results.
    Float(f64),
    /// A complex constant with double-precision components.
    Complex {
        /// Real component.
        real: f64,
        /// Imaginary component.
        imaginary: f64,
    },
    /// A Unicode string constant, stored as UTF-8.
    String(String),
    /// A nominal enum constant.
    Enum(IREnumConstant),
}

impl From<bool> for IRConstant {
    fn from(value: bool) -> Self {
        Self::Bool(value)
    }
}

impl From<i32> for IRConstant {
    fn from(value: i32) -> Self {
        Self::Int(value)
    }
}

impl From<f64> for IRConstant {
    fn from(value: f64) -> Self {
        Self::Float(value)
    }
}

impl From<String> for IRConstant {
    fn from(value: String) -> Self {
        Self::String(value)
    }
}

impl From<&str> for IRConstant {
    fn from(value: &str) -> Self {
        Self::String(value.to_owned())
    }
}

impl From<IREnumConstant> for IRConstant {
    fn from(value: IREnumConstant) -> Self {
        Self::Enum(value)
    }
}
