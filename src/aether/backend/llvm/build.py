from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import tempfile

from aether.pipeline import DEFAULT_SSA_BUILDER, lower_to_verified_ssa
from aether.capabilities import BackendIdentity, validate_backend_capabilities
from aether.ssa.optimizer import SSAOptimizerPipeline

from .backend import LLVMBackend


class LLVMBuildError(Exception):
    """Raised when native LLVM/clang build orchestration fails."""


@dataclass(frozen=True)
class LLVMBuildResult:
    output_path: Path
    llvm_path: Path | None
    clang_stdout: str
    clang_stderr: str


class LLVMBuilder:
    """Build native executables from typed Aether programs via LLVM IR and clang."""

    def __init__(
        self,
        *,
        backend: LLVMBackend | None = None,
        clang: str = "clang",
    ) -> None:
        self._backend = backend or LLVMBackend()
        self._clang = clang

    def emit_llvm(self, typed_program: object) -> str:
        validate_backend_capabilities(typed_program, BackendIdentity.NATIVE)
        module = lower_to_verified_ssa(typed_program, builder=DEFAULT_SSA_BUILDER)
        module = SSAOptimizerPipeline(verify_after_each=True).run(module)
        return self._backend.emit(module)

    def build(
        self,
        typed_program: object,
        *,
        output_path: Path,
        keep_llvm: bool = False,
    ) -> LLVMBuildResult:
        llvm_ir = self.emit_llvm(typed_program)
        output_path = output_path.resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if keep_llvm:
            llvm_path = self._kept_llvm_path(output_path)
            llvm_path.write_text(llvm_ir, encoding="utf-8")
            return self._run_clang(llvm_path, output_path, kept_llvm_path=llvm_path)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                suffix=".ll",
                prefix="aether-",
                delete=False,
            ) as temporary:
                temporary.write(llvm_ir)
                temporary_path = Path(temporary.name)
            return self._run_clang(temporary_path, output_path, kept_llvm_path=None)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _run_clang(
        self,
        llvm_path: Path,
        output_path: Path,
        *,
        kept_llvm_path: Path | None,
    ) -> LLVMBuildResult:
        clang_path = shutil.which(self._clang)
        if clang_path is None:
            raise LLVMBuildError("clang is required to build native executables.")

        try:
            completed = subprocess.run(
                [clang_path, str(llvm_path), "-o", str(output_path)],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise LLVMBuildError(
                "clang is required to build native executables."
            ) from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            if detail:
                raise LLVMBuildError(detail)
            raise LLVMBuildError(
                f"clang failed with exit code {completed.returncode}."
            )

        return LLVMBuildResult(
            output_path=output_path,
            llvm_path=kept_llvm_path,
            clang_stdout=completed.stdout,
            clang_stderr=completed.stderr,
        )

    @staticmethod
    def _kept_llvm_path(output_path: Path) -> Path:
        if output_path.suffix:
            return output_path.with_name(f"{output_path.name}.ll")
        return output_path.with_suffix(".ll")
