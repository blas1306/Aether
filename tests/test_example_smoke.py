"""
Smoke tests for non-interactive Aether examples.

These tests execute example files to ensure they run without errors.
"""

from __future__ import annotations

from pathlib import Path
import tempfile
import sys

import pytest

from aether.runner import run_aether


def get_examples_dir() -> Path:
    """Get the examples directory relative to the project root."""
    tests_dir = Path(__file__).parent
    return tests_dir.parent / "examples"


def copy_examples_to_source_dir(source_dir: Path, examples_to_copy: list[str]) -> None:
    """Copy example files to a source directory for testing.
    
    Args:
        source_dir: The destination directory (e.g., src/aether)
        examples_to_copy: List of relative paths from examples/ (e.g., ["structs/Geometry.ae"])
    """
    examples_dir = get_examples_dir()
    for example_path in examples_to_copy:
        src_file = examples_dir / example_path
        dst_file = source_dir / Path(example_path).name
        
        if not src_file.exists():
            pytest.skip(f"Example file not found: {example_path}")
        
        dst_file.parent.mkdir(parents=True, exist_ok=True)
        dst_file.write_text(src_file.read_text(encoding="utf-8"), encoding="utf-8")


@pytest.fixture
def temp_project(tmp_path):
    """Create a temporary Aether project directory."""
    project = tmp_path / "project"
    source_dir = project / "src" / "aether"
    source_dir.mkdir(parents=True)
    
    return {
        "root": project,
        "source_dir": source_dir,
    }


class TestStructsExample:
    """Test the structs example: Point with field access."""
    
    def test_structs_geometry_and_main(self, temp_project, monkeypatch, capsys):
        """Test Geometry.ae (struct definition) with main.ae (struct usage)."""
        from aether_lsp.run_file import main
        
        project = temp_project
        source_dir = project["source_dir"]
        
        # Set up Geometry package
        geometry_file = source_dir / "Geometry.ae"
        geometry_file.write_text(
            """
package Geometry;

public struct Point {
    double x;
    double y;
}

public alias P = Point;
""",
            encoding="utf-8",
        )
        
        # Set up main that uses Geometry
        main_file = source_dir / "main.ae"
        main_file.write_text(
            """
from Geometry import P;

P p = P(1.0, 2.0);
println(p.x);
println(p.y);
""",
            encoding="utf-8",
        )
        
        monkeypatch.chdir(project["root"])
        
        exit_code = main([str(main_file)])
        
        captured = capsys.readouterr()
        assert exit_code == 0, f"Expected exit code 0, got {exit_code}.\nstderr: {captured.err}"
        assert "1.0" in captured.out
        assert "2.0" in captured.out


def test_struct_constructor_and_equality_example_runs() -> None:
    example_path = get_examples_dir() / "structs" / "custom_constructor_and_equality.ae"

    result = run_aether(example_path.read_text(encoding="utf-8"))

    assert result.output == "4\n4\ntrue\ntrue\n"


class TestLinearAlgebraExamples:
    """Test linear algebra examples."""
    
    def test_basic_matrix_operations(self, temp_project, monkeypatch, capsys):
        """Test basic matrix and vector operations."""
        from aether_lsp.run_file import main
        
        project = temp_project
        source_dir = project["source_dir"]
        
        test_file = source_dir / "basic_ops.ae"
        test_file.write_text(
            """
import Math.LinearAlgebra

A = [1 2; 3 4];
println(A);

B = Math.LinearAlgebra.transpose(A);
println(B);

v = [1; 2];
println(v);
""",
            encoding="utf-8",
        )
        
        monkeypatch.chdir(project["root"])
        
        exit_code = main([str(test_file)])
        
        captured = capsys.readouterr()
        assert exit_code == 0, f"Expected exit code 0, got {exit_code}.\nstderr: {captured.err}"
        # Just check that it runs without error; don't validate exact output format


class TestNonlinearSystemsExample:
    """Test non-linear systems solver example."""
    
    @pytest.mark.skip(reason="Newton system example is experimental")
    def test_newton_system(self, temp_project, monkeypatch, capsys):
        """Test Newton's method for solving non-linear systems.
        
        This example is experimental; the solver may not be fully tested.
        """
        from aether_lsp.run_file import main
        
        project = temp_project
        source_dir = project["source_dir"]
        
        test_file = source_dir / "newton.ae"
        test_file.write_text(
            r"""
import Math.LinearAlgebra

Vector<double> F(Vector<double> x) {
    Vector<double> F = [x[0]^2 + x[1]^2 - 2, x[0] - x[1]];
    return F;
}

Matrix<double> JF(Vector<double> x) {
    Matrix<double> JF = [2*x[0] 2*x[1]; 1 -1];
    return JF;
}

Vector<double> x0 = [1, 1];
double tol = 1e-8;
int maxiter = 100;

(Vector<double> xn, double res, int iter) SNL(
    Vector<double> x0
    ) {
    Vector<double> xn = x0;
    double res = norm(F(xn));
    int iter = 0;

    while (res > tol && iter < maxiter) {
        z = JF(xn) \ (-F(xn));
        xn = xn + z;
        res = norm(F(xn));
        iter += 1;
    }

    return (xn, res, iter);
}

result, residual, iterations = SNL(x0);
println("Solution: ", result);
println("Residual: ", residual);
println("Iterations: ", iterations);
""",
            encoding="utf-8",
        )
        
        monkeypatch.chdir(project["root"])
        
        exit_code = main([str(test_file)])
        
        captured = capsys.readouterr()
        assert exit_code == 0, f"Expected exit code 0, got {exit_code}.\nstderr: {captured.err}"


class TestInteractiveExamplesNotIncluded:
    """Verify that interactive examples are NOT in smoke tests.
    
    These examples require user input and should not be automated.
    """
    
    def test_interactive_examples_exist(self):
        """Verify interactive examples are in the right location."""
        examples_dir = get_examples_dir()
        interactive_dir = examples_dir / "interactive"
        
        expected_files = [
            "sum_calculator.ae",
            "primes_interactive.ae",
            "fibonacci.ae",
        ]
        
        for filename in expected_files:
            filepath = interactive_dir / filename
            assert filepath.exists(), f"Expected interactive example not found: {filename}"
    
    def test_removed_incomplete_minimos_cuadrados_is_not_a_public_example(self):
        """The unsupported closure-based duplicate must stay out of examples."""
        examples_dir = get_examples_dir()

        assert not (examples_dir / "minimos_cuadrados" / "interactive.ae").exists()
