# CONST-V1 — immutable local and parameter bindings

Estado: **IMPLEMENTADO Y CALIFICADO** en `compiler-next`, Linux x86-64,
2026-09-20.

Documento normativo: [CONST_ARCH_1](CONST_ARCH_1.md).

## Resultado

El lexer y parser admiten `const T name = expression` para locals y `const T
name` para parámetros, incluidos `ref`, `ref mut` y defaults. Los locals const
requieren initializer en la declaración. Fields, globals y const dentro de un
type spelling permanecen cerrados con diagnósticos específicos.

`BindingMutability::{Mutable, Const}` se conserva en AST, signatures, HIR y
MIR. SSA retiene una tabla mínima de bindings source y el origen local de las
definiciones aunque mem2reg elimine el slot. La marca no entra en `TypeData`,
`TypeId`, layout, function types, instance keys, mangling ni LLVM.

## Places, shallow const y ownership

El análisis rechaza replacement del root, Stores sobre fields inline y borrow
mutable de ese storage. Un índice de collection/view o un dereference writable
cruza la frontera shallow: `const ref mut T` conserva write capability y
List/class handles mantienen sus protocolos de mutación interior. Rebind del
descriptor sigue prohibido.

Move del owner root completo permanece legal y usa los estados ordinarios
Owned/Moved/MaybeMoved. Return, calls consumidoras y generics no insertan Clone
ni crean una variante const del tipo. Move parcial desde storage inline const
se rechaza. Cleanup normal y excepcional sigue gobernado por los drop flags
existentes: un initializer que lanza no publica el binding y un root transferido
no se destruye de nuevo.

Los verificadores HIR, MIR y SSA repiten initializer único, ausencia de write o
mutable borrow inline, legitimidad de protocolos handle y preservación de la
metadata. MIR/SSA distinguen Move terminal de Store; LLVM no recibe atributos
`constant`, `readonly`, `noalias` ni `invariant.load` por esta propiedad.

## Qualification

`crates/aether-driver/tests/const_v1.rs` cubre runtime initializers, Copy,
defaults, refs, List/class handles, structs, owners, Move/return, use-after-move,
generics, Function values, unwind, contexts cerrados, metadata y corrupciones
HIR/MIR/SSA. Los casos nativos se ejecutan en O0 y O2 y comparan prototypes
físicos de parámetros mutable/const.

Los gates de cierre son:

```text
cargo test --workspace
cargo fmt --all --check
cargo clippy --workspace --all-targets -- -D warnings
git diff --check
bash compiler-next/tests/run-differential.sh
```
