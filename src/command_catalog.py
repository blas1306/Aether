from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommandSuggestion:
    name: str
    insert_text: str
    signature: str
    description: str
    category: str
    label: str | None = None
    kind: str = "command"
    source: str = "catalog"
    priority: int = 100
    match_text: str | None = None
    cursor_backtrack: int | None = None
    cursor_selection_length: int | None = None


def _entry(
    name: str,
    description: str,
    category: str,
    *,
    insert_text: str | None = None,
    signature: str | None = None,
    cursor_backtrack: int | None = None,
) -> CommandSuggestion:
    resolved_insert = insert_text or name
    resolved_signature = signature or resolved_insert
    resolved_backtrack = cursor_backtrack
    if resolved_backtrack is None and resolved_insert.endswith("()"):
        resolved_backtrack = 1
    return CommandSuggestion(
        name=name,
        insert_text=resolved_insert,
        signature=resolved_signature,
        description=description,
        category=category,
        label=name,
        kind="command",
        source="catalog",
        priority=100,
        match_text=name,
        cursor_backtrack=resolved_backtrack,
    )


def _greek_entries() -> tuple[CommandSuggestion, ...]:
    lower = (
        "alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta",
        "iota", "kappa", "lambda", "mu", "nu", "xi", "omicron", "pi", "rho",
        "sigma", "tau", "upsilon", "phi", "chi", "psi", "omega",
    )
    upper = ("Gamma", "Delta", "Theta", "Lambda", "Xi", "Pi", "Sigma", "Upsilon", "Phi", "Psi", "Omega")
    entries = [
        _entry(f"\\{name}", f"Greek symbol {name}.", "greek")
        for name in lower + upper
    ]
    return tuple(entries)


BASE_ENTRIES: tuple[CommandSuggestion, ...] = (
    _entry(r"\abs()", "Absolute value or modulus.", "functions"),
    _entry(r"\adj()", "Conjugate transpose (adjoint) of a matrix.", "linear_algebra"),
    _entry(r"\arccos()", "Inverse cosine.", "functions"),
    _entry(r"\arcsin()", "Inverse sine.", "functions"),
    _entry(r"\arctan()", "Inverse tangent.", "functions"),
    _entry(r"\angle()", "Principal angle of a complex value.", "complex"),
    _entry(r"\benchmark", "Run a benchmark.", "workspace", insert_text=r"\benchmark ", signature=r"\benchmark[loops] <code>"),
    _entry(r"\ceil()", "Ceiling function.", "functions"),
    _entry(r"\clean", "Clear the console output.", "workspace"),
    _entry(r"\clear", "Clear one name or all variables.", "workspace", insert_text=r"\clear ", signature=r"\clear <name>|all"),
    _entry(r"\columns()", "Number of columns of a matrix.", "linear_algebra"),
    _entry(r"\conj()", "Complex conjugate.", "complex"),
    _entry(r"\cos()", "Cosine function.", "functions"),
    _entry(r"\cosh()", "Hyperbolic cosine.", "functions"),
    _entry(r"\definner()", "Define a custom inner product.", "inner_products"),
    _entry(r"\defnorm()", "Define a custom norm.", "norms"),
    _entry(r"\det()", "Determinant of a matrix.", "linear_algebra"),
    _entry(r"\Diag()", "Build a diagonal matrix.", "linear_algebra"),
    _entry(r"\diag()", "Extract the diagonal of a matrix.", "linear_algebra"),
    _entry(r"\diff()", "Differentiate an expression.", "calculus"),
    _entry(r"\dsolve()", "Solve a differential equation.", "calculus"),
    _entry(r"\e", "Euler's number.", "symbols"),
    _entry(r"\error()", "Print an error-style message.", "workspace"),
    _entry(r"\exp()", "Exponential function.", "functions"),
    _entry(r"\figure()", "Create or select a figure.", "plotting"),
    _entry(r"\floor()", "Floor function.", "functions"),
    _entry(r"\format()", "Set the global numeric display format.", "workspace"),
    _entry(r"\frac{}", "Fraction template.", "functions", insert_text=r"\frac{}{}", signature=r"\frac{num}{den}", cursor_backtrack=3),
    _entry(r"\functions", "List user-defined functions.", "workspace"),
    _entry(r"\grid()", "Toggle plot grid on or off.", "plotting"),
    _entry(r"\help", "Show help for a symbol or command.", "workspace", insert_text=r"\help ", signature=r"\help <name>"),
    _entry(r"\hold()", "Toggle plot hold on or off.", "plotting"),
    _entry(r"\Im()", "Imaginary part of an expression.", "complex"),
    _entry(r"\infty", "Infinity symbol.", "symbols"),
    _entry(r"\inner()", "Compute an inner product.", "inner_products"),
    _entry(r"\int()", "Symbolic or numeric integral.", "calculus"),
    _entry(r"\inv()", "Matrix inverse.", "linear_algebra"),
    _entry(r"\LDU()", "LDU factorization.", "linear_algebra"),
    _entry(r"\legend()", "Configure or show the plot legend.", "plotting"),
    _entry(r"\linspace()", "Evenly spaced values.", "arrays"),
    _entry(r"\length()", "Return the length of a vector. Scalars return 1; matrices are not accepted.", "arrays"),
    _entry(r"\listinners", "List available inner products.", "inner_products"),
    _entry(r"\listnorms", "List available norms.", "norms"),
    _entry(r"\ln()", "Natural logarithm.", "functions"),
    _entry(r"\LU()", "LU factorization.", "linear_algebra"),
    _entry(r"\max()", "Maximum value.", "functions"),
    _entry(r"\min()", "Minimum value.", "functions"),
    _entry(r"\N()", "Null space of a matrix.", "linear_algebra"),
    _entry(
        r"\nchoosek(n,k)",
        "Return the binomial coefficient C(n,k) for nonnegative integers with 0 <= k <= n.",
        "functions",
        insert_text=r"\nchoosek()",
        signature=r"\nchoosek(n,k)",
        cursor_backtrack=1,
    ),
    _entry(r"\norm()", "Compute a norm.", "norms"),
    _entry(r"\NR()", "Newton-Raphson root finder.", "calculus"),
    _entry(r"\nthroot()", "Nth root.", "functions"),
    _entry(r"\numel()", "Return the total number of elements.", "arrays"),
    _entry(r"\ode()", "Solve or work with ordinary differential equations.", "calculus"),
    _entry(r"\ones()", "Create a one-filled array.", "arrays"),
    _entry(r"\opt", "Toggle debug optimizations.", "workspace", insert_text=r"\opt on", signature=r"\opt on|off"),
    _entry(r"\orth()", "Orthogonal basis or projection helper.", "linear_algebra"),
    _entry(r"\plot()", "Create a 2D plot.", "plotting"),
    _entry(r"\plot3()", "Create a 3D plot.", "plotting"),
    _entry(r"\polar()", "Polar form of a complex value.", "complex"),
    _entry(r"\print()", "Print values or formatted text.", "workspace"),
    _entry(r"\prod()", "Product command.", "calculus"),
    _entry(r"\Psinv()", "Moore-Penrose pseudoinverse.", "linear_algebra"),
    _entry(r"\QR()", "QR factorization.", "linear_algebra"),
    _entry(r"\QR1()", "Reduced QR factorization.", "linear_algebra"),
    _entry(r"\R()", "Column space of a matrix.", "linear_algebra"),
    _entry(r"\rand()", "Random values.", "arrays"),
    _entry(r"\randi()", "Random integers.", "arrays"),
    _entry(r"\Re()", "Real part of an expression.", "complex"),
    _entry(r"\reset", "Reset the interactive environment.", "workspace"),
    _entry(r"\rg()", "Matrix rank.", "linear_algebra"),
    _entry(r"\rows()", "Number of rows of a matrix.", "linear_algebra"),
    _entry(r"\Schur()", "Schur decomposition of a matrix.", "linear_algebra"),
    _entry(r"\sign()", "Sign function.", "functions"),
    _entry(r"\sin()", "Sine function.", "functions"),
    _entry(r"\sinh()", "Hyperbolic sine.", "functions"),
    _entry(r"\size()", "Return dimensions of a matrix.", "arrays"),
    _entry(r"\solve()", "Solve algebraic equations.", "calculus"),
    _entry(r"\sort()", "Sort a vector or matrix.", "arrays"),
    _entry(r"\Eig()", "Diagonalization of a matrix.", "linear_algebra"),
    _entry(r"\Spec()", "Spectral descomposition of a matrix.", "linear_algebra"),
    _entry(r"\sqrt()", "Square root.", "functions"),
    _entry(r"\sum()", "Summation command.", "calculus"),
    _entry(r"\SVD()", "Singular value decomposition.", "linear_algebra"),
    _entry(r"\T()", "Transpose of a matrix.", "linear_algebra"),
    _entry(r"\tan()", "Tangent function.", "functions"),
    _entry(r"\tanh()", "Hyperbolic tangent.", "functions"),
    _entry(r"\time", "Measure execution time once.", "workspace", insert_text=r"\time ", signature=r"\time <code>"),
    _entry(r"\title()", "Set the current plot title.", "plotting"),
    _entry(r"\tr()", "Trace of a matrix.", "linear_algebra"),
    _entry(r"\vap()", "Eigenvalues of a matrix.", "linear_algebra"),
    _entry(r"\vars", "Show current workspace variables.", "workspace"),
    _entry(r"\vep()", "Eigenvectors of a matrix.", "linear_algebra"),
    _entry(r"\who", "List defined variables.", "workspace"),
    _entry(r"\whos", "List variables with details.", "workspace"),
    _entry(r"\xlabel()", "Set the x-axis label.", "plotting"),
    _entry(r"\ylabel()", "Set the y-axis label.", "plotting"),
    _entry(r"\zeros()", "Create a zero-filled array.", "arrays"),
)


COMMAND_CATALOG: tuple[CommandSuggestion, ...] = BASE_ENTRIES + _greek_entries()
