//! Experimental Python adapter over the transport-independent compiler core.
//!
//! This crate owns Python conversion and exception translation only. Compiler
//! semantics remain in `aether-verifier::CompilerCore`, which is also consumed
//! by the persistent companion.

use std::sync::Mutex;

use aether_ir::wire::IRModuleDTO;
use aether_verifier::{
    CompilationSession, CompilerCore, CompilerError, CompilerErrorKind, CompilerPhase,
};
use pyo3::create_exception;
use pyo3::exceptions::PyException;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyModule};

create_exception!(
    _aether_core,
    AetherCoreError,
    PyException,
    "Base class for structured Aether compiler-core failures."
);
create_exception!(
    _aether_core,
    AetherCompilerError,
    AetherCoreError,
    "A deterministic compiler or semantic failure."
);
create_exception!(
    _aether_core,
    AetherBindingError,
    AetherCoreError,
    "Malformed input or misuse at the Python/Rust binding boundary."
);
create_exception!(
    _aether_core,
    AetherInternalCompilerError,
    AetherCoreError,
    "An internal compiler-core invariant failure."
);

#[derive(Debug)]
struct BindingFailure {
    category: &'static str,
    phase: &'static str,
    code: &'static str,
    message: String,
}

fn phase_name(phase: CompilerPhase) -> &'static str {
    match phase {
        CompilerPhase::LifecycleNormalization => "lifecycle_normalization",
        CompilerPhase::SsaLowering => "ssa_lowering",
        CompilerPhase::SsaVerification => "ssa_verification",
        CompilerPhase::CoreState => "core_state",
    }
}

fn structured_error(
    py: Python<'_>,
    error: PyErr,
    kind: &'static str,
    category: &str,
    phase: &str,
    code: &str,
    function: Option<String>,
    block: Option<String>,
    source_location: Option<(Option<String>, u64, u64)>,
) -> PyErr {
    let value = error.value(py);
    // These assignments target ordinary exception instance dictionaries. If
    // Python itself rejects one, returning the original fail-closed exception
    // is preferable to masking the compiler failure with another exception.
    let _ = value.setattr("kind", kind);
    let _ = value.setattr("category", category);
    let _ = value.setattr("phase", phase);
    let _ = value.setattr("code", code);
    let _ = value.setattr("function", function);
    let _ = value.setattr("block", block);
    let _ = value.setattr("source_location", source_location);
    error
}

fn core_error(py: Python<'_>, error: CompilerError) -> PyErr {
    let location = error
        .source_location
        .map(|value| (value.path, value.line, value.column));
    let function = error.function;
    let block = error.block;
    let phase = phase_name(error.phase);
    match error.kind {
        CompilerErrorKind::Compiler => structured_error(
            py,
            AetherCompilerError::new_err(error.message),
            "compiler",
            error.category,
            phase,
            error.code,
            function,
            block,
            location,
        ),
        CompilerErrorKind::Internal => structured_error(
            py,
            AetherInternalCompilerError::new_err(error.message),
            "internal",
            error.category,
            phase,
            error.code,
            function,
            block,
            location,
        ),
    }
}

fn binding_error(py: Python<'_>, error: BindingFailure) -> PyErr {
    structured_error(
        py,
        AetherBindingError::new_err(error.message),
        "binding",
        error.category,
        error.phase,
        error.code,
        None,
        None,
        None,
    )
}

/// Rust-owned compilation state. The mutex makes state transitions explicit,
/// reentrant-safe, and usable while the calling Python thread releases the GIL.
#[pyclass(name = "CompilationSession")]
struct PyCompilationSession {
    inner: Mutex<CompilationSession>,
}

#[pymethods]
impl PyCompilationSession {
    /// Lower and verify SSA in Rust while releasing the GIL.
    fn lower_ssa(&self, py: Python<'_>) -> PyResult<()> {
        let result = py.detach(|| {
            let mut session = self.inner.lock().map_err(|_| BindingFailure {
                category: "core_state",
                phase: "core_state",
                code: "CORE-BIND-STATE-001",
                message: "compiler session lock was poisoned".into(),
            })?;
            session.lower_ssa().map_err(EitherFailure::Core)
        });
        match result {
            Ok(()) => Ok(()),
            Err(EitherFailure::Core(error)) => Err(core_error(py, error)),
            Err(EitherFailure::Binding(error)) => Err(binding_error(py, error)),
        }
    }

    /// Qualification/debug escape hatch; no stage-to-stage core API uses it.
    fn export_ssa_schema_v2<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        let result = py.detach(|| {
            let session = self.inner.lock().map_err(|_| BindingFailure {
                category: "core_state",
                phase: "core_state",
                code: "CORE-BIND-STATE-001",
                message: "compiler session lock was poisoned".into(),
            })?;
            let dto = session
                .export_ssa_schema_v2()
                .map_err(EitherFailure::Core)?;
            serde_json::to_vec(&dto).map_err(|error| {
                EitherFailure::Binding(BindingFailure {
                    category: "result_conversion",
                    phase: "schema_v2_export",
                    code: "CORE-BIND-OUTPUT-001",
                    message: error.to_string(),
                })
            })
        });
        match result {
            Ok(bytes) => Ok(PyBytes::new(py, &bytes)),
            Err(EitherFailure::Core(error)) => Err(core_error(py, error)),
            Err(EitherFailure::Binding(error)) => Err(binding_error(py, error)),
        }
    }
}

enum EitherFailure {
    Core(CompilerError),
    Binding(BindingFailure),
}

impl From<BindingFailure> for EitherFailure {
    fn from(value: BindingFailure) -> Self {
        Self::Binding(value)
    }
}

/// Python-visible factory for compilation-local core sessions.
#[pyclass(name = "CompilerCore")]
#[derive(Default)]
struct PyCompilerCore;

#[pymethods]
impl PyCompilerCore {
    #[new]
    fn new() -> Self {
        Self
    }

    /// Decode schema-v1 exactly once and retain a typed Rust representation.
    fn accept_initial_ir_schema_v1(
        &self,
        py: Python<'_>,
        payload: &[u8],
    ) -> PyResult<PyCompilationSession> {
        // A single copy detaches the input lifetime from Python before the GIL
        // is released. The resulting DTO remains Rust-owned for later stages.
        let owned_payload = payload.to_vec();
        let result = py.detach(move || {
            serde_json::from_slice::<IRModuleDTO>(&owned_payload).map_err(|error| BindingFailure {
                category: "input_schema",
                phase: "initial_ir_import",
                code: "CORE-BIND-INPUT-001",
                message: error.to_string(),
            })
        });
        match result {
            Ok(initial_ir) => Ok(PyCompilationSession {
                inner: Mutex::new(CompilerCore.accept_initial_ir(initial_ir)),
            }),
            Err(error) => Err(binding_error(py, error)),
        }
    }
}

/// Qualification-only in-process extension module.
#[pymodule]
fn _aether_core(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    module.add("QUALIFICATION_ONLY", true)?;
    module.add_class::<PyCompilerCore>()?;
    module.add_class::<PyCompilationSession>()?;
    module.add("AetherCoreError", module.py().get_type::<AetherCoreError>())?;
    module.add(
        "AetherCompilerError",
        module.py().get_type::<AetherCompilerError>(),
    )?;
    module.add(
        "AetherBindingError",
        module.py().get_type::<AetherBindingError>(),
    )?;
    module.add(
        "AetherInternalCompilerError",
        module.py().get_type::<AetherInternalCompilerError>(),
    )?;
    Ok(())
}
