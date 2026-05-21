# MathTeX Studio

> A math-first computational environment for technical writing, numerical computation, and executable scientific documents.

MathTeX Studio combines the workflow of LaTeX, MATLAB/Octave, Jupyter, and scientific computing tools into a single environment focused on mathematical and technical work.

> Aether v0 is now being developed as the next isolated language core for Aether Studio. See the initial specification in [docs/aether/AETHER_V0_SPEC.md](docs/aether/AETHER_V0_SPEC.md).
> Experimental `.ae` files can be opened and run from the editor with the Aether runtime. The lower panel now switches to a persistent Aether REPL for `.ae` files, while `.mtx` files remain supported through the MathLab legacy console during the transition.

Instead of separating:

- computation
- plotting
- symbolic manipulation
- report writing
- PDF generation

into multiple disconnected applications, MathTeX Studio allows everything to happen inside one integrated workflow.

---

# Why MathTeX Studio?

In a traditional workflow, a student or researcher often needs to:

1. Compute results in MATLAB, Octave, Python, or Julia
2. Generate plots separately
3. Export tables manually
4. Copy results into LaTeX
5. Recompile the document every time something changes

MathTeX Studio was created to remove that friction.

The idea is simple:

> write the computation and the document together

When values, equations, tables, or plots change, the final PDF updates automatically.

---

# Main Concepts

MathTeX Studio currently revolves around two complementary formats:

| Format | Purpose |
|---|---|
| `.mtx` | Interactive mathematical scripting |
| `.ae` | Experimental Aether scripts |
| `.mtex` | Executable LaTeX documents |

---

# REPL Transition

The interactive panel is currently runtime-aware:

- `.ae` files use an `Aether REPL` with persistent `AetherSession` state and the `aether>` prompt.
- `.mtx` files keep using the `MathLab Legacy Console` with the `mathlab>` prompt.
- Aether REPL output is intentionally explicit for now: use `print(...)` or `println(...)`. Expression auto-printing, shell execution, completion, and advanced multiline input are not part of this transition step yet.

The REPL UX is still in transition while the rest of the application keeps the existing MathTeX/MathLab workflow.

---

# `.mtx` — Mathematical Scripts

`.mtx` files are designed for:

- numerical experimentation
- reusable functions
- symbolic computation
- plotting
- linear algebra
- numerical methods
- quick calculations

The syntax is heavily inspired by MATLAB and Octave while remaining integrated with the MathTeX runtime.

Example:

```text
A = [1, 2; 3, 4];
b = [5; 6];

x = A | b;

print(x)
```

---

# `.mtex` — Executable Technical Documents

`.mtex` files combine LaTeX with executable code blocks.

This allows documents to:

- execute calculations during compilation
- inject computed values directly into the PDF
- generate plots automatically
- generate tables automatically
- keep documents synchronized with the underlying computation

Typical use cases:

- physics lab reports
- numerical methods assignments
- linear algebra reports
- scientific notes
- engineering documentation
- computational mathematics

---

# Example

```latex
\documentclass{article}
\begin{document}

\section{Linear System}

\begin{code}
A = [1, 2; 3, 4];
b = [5; 6];

x = A | b;
\end{code}

The computed solution is:

\[
x = \var{x}
\]

\end{document}
```

Compilation pipeline:

```text
.mtex → execution → .tex → pdflatex → PDF
```

During compilation, MathTeX Studio:

1. executes the code blocks
2. stores variables in the runtime workspace
3. replaces placeholders such as `\var{x}`
4. generates an intermediate `.tex` file
5. compiles the final PDF automatically

---

# Variable and Expression Injection

## Variable Injection

```latex
\var{x}
```

Injects the value of a computed variable.

Supports indexing:

```latex
\var{A(2,1)}
```

---

## Expression Injection

```latex
\expr{\det(A)}
```

Evaluates and injects a computed expression.

Useful for:

- determinants
- norms
- traces
- symbolic expressions
- computed formulas

---

# Plot Generation

Plots can be generated programmatically and inserted directly into the document.

## Script

```text
f(x) = x.^2 - 2;

\plot(f, -1, 3, name = "graph")
```

## Document

```latex
\plot{graph}
```

---

# Tables

Generated tables can also be embedded automatically.

```latex
\table{results}
```

This is especially useful for:

- experimental measurements
- numerical iterations
- regression outputs
- matrix data

---

# Interactive Notebooks (`.mtn`)

MathTeX Studio also includes an experimental notebook system.

Notebook documents support:

- executable code blocks
- text blocks
- persistent shared workspace
- sequential execution
- output visualization
- export to `.mtex`

The notebook workflow is designed to combine ideas from:

- Jupyter
- MATLAB Live Scripts
- scientific computing notebooks

while remaining deeply integrated with the MathTeX document pipeline.

---

# Features

## Computation

- numerical computation
- symbolic computation
- matrix operations
- linear algebra
- calculus utilities
- equation solving
- element-wise operations
- numerical methods

---

## Document System

- executable LaTeX documents
- automatic PDF generation
- inline variable injection
- inline expression evaluation
- automatic plot insertion
- automatic table insertion
- intermediate `.tex` generation

---

## Interface

- PyQt6 desktop application
- integrated editor
- PDF preview
- CLI fallback mode
- autocomplete system
- diagnostics and error reporting
- project-based workflow

---

## Runtime and Language

- custom parser
- custom AST pipeline
- MATLAB/Octave-inspired syntax
- runtime workspace system
- document execution engine
- execution-aware placeholders

---

# Philosophy

MathTeX Studio is not trying to replace:

- MATLAB
- Octave
- Wolfram Mathematica
- Jupyter
- Overleaf
- Python
- Julia

Instead, the goal is to combine parts of those workflows into a single environment focused on:

> executable mathematical documents

The project is especially oriented toward:

- students
- engineers
- researchers
- scientific computing workflows
- technical education

---

# Screenshots

> Screenshots and demos will be added here.

Suggested future additions:

- editor UI
- notebook UI
- PDF synchronization
- plots
- executable document examples

---

# Installation

## Requirements

- Python 3.11+
- `pdflatex` available in `PATH`
- dependencies from `requirements.txt`
- PyQt6 with QtPdf support

Recommended TeX distributions:

| Platform | Distribution |
|---|---|
| Windows | MiKTeX |
| Linux | TeX Live |
| macOS | MacTeX |

---

## Clone the Repository

```bash
git clone https://github.com/blas1306/MathTeX_Studio.git
cd MathTeX_Studio
```

---

## Create a Virtual Environment

### Linux / macOS

```bash
python -m venv .venv
source .venv/bin/activate
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

---

## Install Dependencies

```bash
python -m pip install -r requirements.txt
```

---

# Running MathTeX Studio

## GUI Mode

```bash
python src/main.py
```

### Experimental CodeMirror Editor

The default editor remains `qt_plain`. To manually start the real app with the
offline CodeMirror prototype for one process, set `AETHER_EDITOR_KIND`:

```bash
AETHER_EDITOR_KIND=codemirror ./.venv/bin/python src/main.py
```

Supported values are `qt_plain`, `experimental`, and `codemirror`. Invalid
values emit a clear warning and fall back to `qt_plain`.

---

## CLI Mode

```bash
python src/main.py --cli
```

Behavior:

- the application attempts to launch the GUI first
- if GUI initialization fails, MathTeX falls back to CLI mode
- `--cli` forces text-only execution

---

# Build Artifacts

When compiling a `.mtex` document, build outputs are generated automatically.

Typical outputs:

```text
build/
├── document.tex
├── document.pdf
├── compile.log
└── document.mtextrace.json
```

The `.mtextrace.json` artifact is used for source mapping and synchronization between `.mtex` source lines and generated LaTeX.

---

# Project Structure

```text
src/        Core source code
tests/      Automated tests
docs/       Documentation
ejemplos/   Example projects and demos
```

Important modules:

| File | Purpose |
|---|---|
| `src/main.py` | Application entry point |
| `src/mtex_executor.py` | `.mtex` execution pipeline |
| `src/latex_lang.py` | Runtime and language integration |
| `src/qt_app.py` | PyQt6 application |
| `src/notebook_*` | Notebook system |

---

# Testing

The project includes an extensive automated test suite.

Run tests with:

```bash
pytest tests -q
```

The test suite covers:

- parser behavior
- runtime execution
- diagnostics
- notebook execution
- Qt workflows
- document compilation
- AST transformations

---

# Example Projects

## Physics Lab Report

Demonstrates:

- experimental measurements
- automatic calculations
- generated plots
- integrated PDF workflow

---

## Linear Algebra Report

Demonstrates:

- matrix operations
- LU factorization
- solving linear systems
- embedded computed results

---

## Newton–Raphson Demo

Demonstrates:

- numerical root finding
- iterative methods
- generated plots
- executable mathematical reports

---

# Current Status

MathTeX Studio is under active development.

The core execution pipeline is already functional and usable, while many parts of the interface and user experience continue to evolve.

Current areas of development include:

- notebook system
- editor UX/UI
- PDF synchronization
- diagnostics
- runtime improvements
- language features
- project workflow

---

# Roadmap Ideas

Potential future directions:

- real-time PDF synchronization
- richer plotting system
- Julia and Python execution blocks
- improved notebook experience
- package/module system
- scientific publishing templates
- interactive widgets
- collaborative editing

---

# AI Assistance Disclaimer

This project has been developed with significant assistance from AI tools.

MathTeX Studio is also part of a broader learning process involving:

- language design
- compiler construction
- scientific computing
- numerical methods
- desktop application development
- LaTeX tooling
- UI/UX design

The long-term goal is to progressively deepen understanding of the system internals and continue evolving the project independently.

---

# Contributing

Contributions, ideas, issue reports, and feedback are welcome.

Formal contribution guidelines are not yet finalized.

---

# License

This project is licensed under the GNU General Public License v3.0 (GPL-3.0).

This means:

- you may use, modify, and distribute the software
- derivative distributed works must also remain open source under GPLv3

See the `LICENSE` file for details.
