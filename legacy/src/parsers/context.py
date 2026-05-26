from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional


@dataclass
class ParserContext:
    """Datos y utilidades compartidas que cada parser necesita."""

    env_ast: Dict[str, Any]
    greek_symbols: Dict[str, Any]
    greek_display: Dict[str, str]
    user_norms: Dict[str, Any]
    user_inners: Dict[str, Any]
    latex_to_python: Callable[[str], str]
    common_symbols: Dict[str, Any]
    expr_to_python: Optional[Callable[[str], str]] = None
    plot_func: Optional[Callable[..., Any]] = None
    plot_backend: Optional[Any] = None
    plot3_func: Optional[Callable[..., Any]] = None
    nr_func: Optional[Callable[..., Any]] = None
    run_line: Optional[Callable[[str], Any]] = None

    def eval_context(self, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Construye un contexto de evaluación actualizado."""
        ctx: Dict[str, Any] = dict(self.greek_symbols)
        ctx.update(self.common_symbols)
        ctx.update(self.env_ast)
        for value in self.env_ast.values():
            if isinstance(value, (str, bytes)):
                continue

            try:
                free_symbols = getattr(value, "free_symbols", None)
            except Exception:
                free_symbols = None
            if free_symbols:
                for sym in free_symbols:
                    ctx.setdefault(str(sym), sym)

            if isinstance(value, (tuple, list, set)):
                for item in value:
                    if getattr(item, "is_Symbol", False):
                        ctx.setdefault(str(item), item)
        ctx["env"] = self.env_ast
        ctx["env_ast"] = self.env_ast
        lambda_alias = self.env_ast.get("lambda", self.greek_symbols.get("lambda"))
        if lambda_alias is not None:
            ctx["lambda_kw"] = lambda_alias
        if self.run_line:
            ctx["mathtex"] = self.run_line
        if extra:
            ctx.update(extra)
        return ctx
