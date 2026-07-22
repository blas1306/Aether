//! Named values, storage locations, and parameters.

use crate::IRType;

/// A named immutable IR value.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct IRValue {
    /// Value name without the textual IR `%` prefix.
    pub name: String,
    /// Static IR type.
    pub r#type: IRType,
}

impl IRValue {
    /// Creates a named value.
    pub fn new(name: impl Into<String>, r#type: IRType) -> Self {
        Self {
            name: name.into(),
            r#type,
        }
    }
}

/// An addressable owning location, distinct from an immutable IR value.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct IRStorage {
    /// Storage name without the textual IR `%` prefix.
    pub name: String,
    /// Static type of the stored value.
    pub r#type: IRType,
}

impl IRStorage {
    /// Creates a named storage location.
    pub fn new(name: impl Into<String>, r#type: IRType) -> Self {
        Self {
            name: name.into(),
            r#type,
        }
    }
}

impl From<IRStorage> for IRValue {
    fn from(storage: IRStorage) -> Self {
        Self {
            name: storage.name,
            r#type: storage.r#type,
        }
    }
}

impl From<&IRStorage> for IRValue {
    fn from(storage: &IRStorage) -> Self {
        Self {
            name: storage.name.clone(),
            r#type: storage.r#type.clone(),
        }
    }
}

/// A tagged operand that may be an immutable value or an addressable storage location.
///
/// Lifecycle copy/assignment sources and return operands use this representation
/// where their canonical value/storage distinction affects verification.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum LifecycleSource {
    /// An immutable SSA value, including a function parameter.
    Value(IRValue),
    /// An addressable owning storage location.
    Storage(IRStorage),
}

impl LifecycleSource {
    /// Returns the source's static IR type.
    #[must_use]
    pub fn r#type(&self) -> &IRType {
        match self {
            Self::Value(value) => &value.r#type,
            Self::Storage(storage) => &storage.r#type,
        }
    }
}

impl From<IRValue> for LifecycleSource {
    fn from(value: IRValue) -> Self {
        Self::Value(value)
    }
}

impl From<IRStorage> for LifecycleSource {
    fn from(storage: IRStorage) -> Self {
        Self::Storage(storage)
    }
}

/// A declared function parameter.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct IRParameter {
    /// Parameter name without the textual IR `%` prefix.
    pub name: String,
    /// Static parameter type.
    pub r#type: IRType,
}

impl IRParameter {
    /// Creates a named parameter.
    pub fn new(name: impl Into<String>, r#type: IRType) -> Self {
        Self {
            name: name.into(),
            r#type,
        }
    }
}

impl From<IRParameter> for IRValue {
    fn from(parameter: IRParameter) -> Self {
        Self {
            name: parameter.name,
            r#type: parameter.r#type,
        }
    }
}

impl From<&IRParameter> for IRValue {
    fn from(parameter: &IRParameter) -> Self {
        Self {
            name: parameter.name.clone(),
            r#type: parameter.r#type.clone(),
        }
    }
}

impl From<IRParameter> for LifecycleSource {
    fn from(parameter: IRParameter) -> Self {
        Self::Value(parameter.into())
    }
}
