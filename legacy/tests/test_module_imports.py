from __future__ import annotations

import io
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

import pytest

from latex_lang import (
    _LOADED_MODULES,
    change_working_dir,
    env_ast,
    ejecutar_linea,
    get_working_dir,
    reset_environment,
)


def _run(line: str) -> str:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ejecutar_linea(line)
    return buffer.getvalue()


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@contextmanager
def _working_dir(path: Path):
    previous_dir = get_working_dir()
    assert change_working_dir(path)
    try:
        yield
    finally:
        change_working_dir(previous_dir)


@pytest.fixture(autouse=True)
def _reset_runtime():
    previous_dir = get_working_dir()
    reset_environment()
    yield
    change_working_dir(previous_dir)
    reset_environment()


def test_import_module_exposes_module_object_and_attributes(tmp_path: Path):
    _write(
        tmp_path / "basic.mtx",
        "value = 7;\n"
        "function y = addOne(x)\n"
        "    y = x + 1;\n"
        "end\n",
    )

    with _working_dir(tmp_path):
        output = _run("import basic")
        _run("copied = basic.value;")
        _run("result = basic.addOne(4);")

    assert output == ""
    assert "basic" in env_ast
    assert env_ast["copied"] == 7
    assert float(env_ast["result"]) == pytest.approx(5.0)


def test_import_dotted_module_binds_last_segment_only(tmp_path: Path):
    _write(tmp_path / "metodos" / "newton.mtx", "tag = 11;\n")

    with _working_dir(tmp_path):
        output = _run("import metodos.newton")
        _run("value = newton.tag;")

    assert output == ""
    assert "newton" in env_ast
    assert "metodos" not in env_ast
    assert env_ast["value"] == 11


def test_from_import_multiple_symbols(tmp_path: Path):
    _write(tmp_path / "multi.mtx", "a = 1;\nb = 2;\n")

    with _working_dir(tmp_path):
        output = _run("from multi import a, b")

    assert output == ""
    assert env_ast["a"] == 1
    assert env_ast["b"] == 2


def test_private_symbols_are_not_exported_or_accessible(tmp_path: Path):
    _write(
        tmp_path / "private.mtx",
        "_x = 1;\n"
        "visible = 2;\n"
        "function y = _hidden(x)\n"
        "    y = x + _x;\n"
        "end\n"
        "function y = publicFn(x)\n"
        "    y = x + visible;\n"
        "end\n",
    )

    with _working_dir(tmp_path):
        hidden_var_output = _run("from private import _x")
        hidden_func_output = _run("from private import _hidden")
        _run("import private")
        private_attr_output = _run("secret = private._x;")
        public_output = _run("ok = private.publicFn(3);")

    assert "does not export '_x'" in hidden_var_output
    assert "does not export '_hidden'" in hidden_func_output
    assert "Module 'private' has no attribute '_x'" in private_attr_output
    assert public_output == ""
    assert float(env_ast["ok"]) == pytest.approx(5.0)


def test_from_import_star_fails_explicitly(tmp_path: Path):
    _write(tmp_path / "star.mtx", "a = 1;\n")

    with _working_dir(tmp_path):
        output = _run("from star import *")

    assert "not supported" in output
    assert "a" not in env_ast


def test_module_cache_reuses_loaded_module(tmp_path: Path):
    _write(tmp_path / "cached.mtx", "value = 1;\n")

    with _working_dir(tmp_path):
        _run("import cached")
        first_module = env_ast["cached"]
        _run("import cached")
        _run("from cached import value")

    assert env_ast["cached"] is first_module
    assert _LOADED_MODULES["cached"] is first_module
    assert len(_LOADED_MODULES) == 1
    assert env_ast["value"] == 1


def test_reset_environment_clears_module_cache(tmp_path: Path):
    _write(tmp_path / "resetmod.mtx", "value = 1;\n")

    with _working_dir(tmp_path):
        _run("import resetmod")

    assert _LOADED_MODULES
    reset_environment()
    assert not _LOADED_MODULES
    assert "resetmod" not in env_ast


def test_circular_imports_are_detected(tmp_path: Path):
    _write(tmp_path / "a.mtx", "import b\n")
    _write(tmp_path / "b.mtx", "import a\n")

    with _working_dir(tmp_path):
        output = _run("import a")

    assert "Circular import detected: a -> b -> a" in output
    assert "a" not in env_ast
    assert not _LOADED_MODULES


def test_module_functions_use_module_definition_scope_for_import_and_from_import(tmp_path: Path):
    _write(
        tmp_path / "scoped.mtx",
        "a = 10;\n"
        "function y = f(x)\n"
        "    y = x + a;\n"
        "end\n",
    )

    with _working_dir(tmp_path):
        _run("a = 3;")
        _run("import scoped")
        _run("direct = scoped.f(2);")
        _run("from scoped import f")
        _run("selective = f(2);")

    assert float(env_ast["direct"]) == pytest.approx(12.0)
    assert float(env_ast["selective"]) == pytest.approx(12.0)


def test_caller_function_passed_to_module_keeps_caller_scope(tmp_path: Path):
    _write(
        tmp_path / "callbacks.mtx",
        "a = 100;\n"
        "function y = applyTwice(f, x)\n"
        "    y = f(x) + f(x);\n"
        "end\n",
    )

    with _working_dir(tmp_path):
        _run("a = 3;")
        _run("function y = addA(x)")
        _run("y = x + a;")
        _run("end")
        _run("import callbacks")
        _run("result = callbacks.applyTwice(addA, 2);")

    assert float(env_ast["result"]) == pytest.approx(10.0)


def test_direct_run_prints_banner_before_script_output(tmp_path: Path):
    _write(tmp_path / "banner.mtx", "x = 42;\n")

    with _working_dir(tmp_path):
        output = _run(r"\run banner.mtx")

    assert ">> banner.mtx" in output
    assert env_ast["x"] == 42


def test_import_does_not_print_run_banner(tmp_path: Path):
    _write(tmp_path / "quiet.mtx", "x = 1;\n")

    with _working_dir(tmp_path):
        output = _run("import quiet")

    assert output == ""
    assert "quiet" in env_ast


def test_missing_module_attribute_reports_clear_error(tmp_path: Path):
    _write(tmp_path / "attrs.mtx", "value = 1;\n")

    with _working_dir(tmp_path):
        _run("import attrs")
        output = _run("bad = attrs.foo;")

    assert "Module 'attrs' has no attribute 'foo'" in output
    assert "bad" not in env_ast


def test_importing_mtex_document_as_module_fails_clearly(tmp_path: Path):
    _write(
        tmp_path / "docmod.mtex",
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\end{document}\n",
    )

    with _working_dir(tmp_path):
        output = _run("import docmod")

    assert "only .mtx files are importable" in output
    assert "docmod" not in env_ast
