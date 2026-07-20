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
