//! Strict JSON entry point for the complete schema-v1 module boundary.

use std::collections::HashSet;
use std::error::Error;
use std::fmt;

use serde::de::{MapAccess, SeqAccess, Visitor};
use serde::{Deserialize, Deserializer};
use serde_json::{Map, Number, Value};

use crate::wire::{IR_SCHEMA_VERSION, IRModuleDTO};
use crate::{IRImportError, IRModule, import_module};

/// A failure at one of the distinct JSON-to-owned-module boundary layers.
#[derive(Debug)]
pub enum IRModuleJsonImportError {
    /// The input is not strict standard JSON, including duplicate object keys.
    Json {
        /// JSON parser failure, including its line and column when available.
        source: serde_json::Error,
    },
    /// Valid strict JSON does not conform to the frozen wire DTO schema.
    Wire {
        /// Serde wire-schema decoding failure.
        source: serde_json::Error,
    },
    /// The root carries an integer schema version unsupported by this importer.
    SchemaVersion {
        /// Typed importer error retaining received and supported versions.
        source: IRImportError,
    },
    /// The wire DTO contains a shape the owned Rust IR cannot represent.
    Import {
        /// Fully contextual structural importer failure.
        source: IRImportError,
    },
}

impl fmt::Display for IRModuleJsonImportError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Json { source } => write!(formatter, "invalid IR module JSON: {source}"),
            Self::Wire { source } => write!(formatter, "invalid IR module wire DTO: {source}"),
            Self::SchemaVersion { source } => write!(formatter, "{source}"),
            Self::Import { source } => {
                write!(formatter, "IR module DTO could not be imported: {source}")
            }
        }
    }
}

impl Error for IRModuleJsonImportError {
    fn source(&self) -> Option<&(dyn Error + 'static)> {
        match self {
            Self::Json { source } | Self::Wire { source } => Some(source),
            Self::SchemaVersion { source } | Self::Import { source } => Some(source),
        }
    }
}

/// Decode strict schema-v1 JSON and reconstruct an owned Rust IR module.
///
/// Duplicate keys are rejected in every object before wire decoding. This is a
/// structural ingestion boundary only: it does not run the semantic verifier,
/// construct a CFG, or enter the compiler pipeline.
pub fn import_module_json(json: &str) -> Result<IRModule, IRModuleJsonImportError> {
    let value = parse_strict_json(json)?;

    if let Some(received) = value
        .as_object()
        .and_then(|root| root.get("schema_version"))
        .and_then(Value::as_i64)
        .filter(|received| *received != IR_SCHEMA_VERSION)
    {
        return Err(IRModuleJsonImportError::SchemaVersion {
            source: IRImportError::UnsupportedSchemaVersion {
                received,
                supported: IR_SCHEMA_VERSION,
            },
        });
    }

    let dto: IRModuleDTO =
        serde_json::from_value(value).map_err(|source| IRModuleJsonImportError::Wire { source })?;
    import_module(&dto).map_err(|source| IRModuleJsonImportError::Import { source })
}

fn parse_strict_json(json: &str) -> Result<Value, IRModuleJsonImportError> {
    let mut deserializer = serde_json::Deserializer::from_str(json);
    let value = StrictJsonValue::deserialize(&mut deserializer)
        .map_err(|source| IRModuleJsonImportError::Json { source })?;
    deserializer
        .end()
        .map_err(|source| IRModuleJsonImportError::Json { source })?;
    Ok(value.0)
}

struct StrictJsonValue(Value);

impl<'de> Deserialize<'de> for StrictJsonValue {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        deserializer.deserialize_any(StrictJsonVisitor)
    }
}

struct StrictJsonVisitor;

impl<'de> Visitor<'de> for StrictJsonVisitor {
    type Value = StrictJsonValue;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("a standard JSON value without duplicate object keys")
    }

    fn visit_bool<E>(self, value: bool) -> Result<Self::Value, E> {
        Ok(StrictJsonValue(Value::Bool(value)))
    }

    fn visit_i64<E>(self, value: i64) -> Result<Self::Value, E> {
        Ok(StrictJsonValue(Value::Number(value.into())))
    }

    fn visit_u64<E>(self, value: u64) -> Result<Self::Value, E> {
        Ok(StrictJsonValue(Value::Number(value.into())))
    }

    fn visit_f64<E>(self, value: f64) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        Number::from_f64(value)
            .map(Value::Number)
            .map(StrictJsonValue)
            .ok_or_else(|| E::custom("non-finite floating-point JSON value"))
    }

    fn visit_str<E>(self, value: &str) -> Result<Self::Value, E>
    where
        E: serde::de::Error,
    {
        self.visit_string(value.to_owned())
    }

    fn visit_string<E>(self, value: String) -> Result<Self::Value, E> {
        Ok(StrictJsonValue(Value::String(value)))
    }

    fn visit_none<E>(self) -> Result<Self::Value, E> {
        Ok(StrictJsonValue(Value::Null))
    }

    fn visit_unit<E>(self) -> Result<Self::Value, E> {
        Ok(StrictJsonValue(Value::Null))
    }

    fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
    where
        A: SeqAccess<'de>,
    {
        let mut values = Vec::with_capacity(sequence.size_hint().unwrap_or(0));
        while let Some(value) = sequence.next_element::<StrictJsonValue>()? {
            values.push(value.0);
        }
        Ok(StrictJsonValue(Value::Array(values)))
    }

    fn visit_map<A>(self, mut object: A) -> Result<Self::Value, A::Error>
    where
        A: MapAccess<'de>,
    {
        let mut keys = HashSet::with_capacity(object.size_hint().unwrap_or(0));
        let mut values = Map::new();
        while let Some(key) = object.next_key::<String>()? {
            if !keys.insert(key.clone()) {
                return Err(serde::de::Error::custom(format_args!(
                    "duplicate IR module JSON object key '{key}'"
                )));
            }
            let value = object.next_value::<StrictJsonValue>()?;
            values.insert(key, value.0);
        }
        Ok(StrictJsonValue(Value::Object(values)))
    }
}
