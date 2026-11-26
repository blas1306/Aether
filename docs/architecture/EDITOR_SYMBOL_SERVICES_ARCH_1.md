# EDITOR-SYMBOL-SERVICES-ARCH-1 — servicios semánticos de símbolos

Estado: **ARCH CLOSED; IMPLEMENTACIÓN NO INICIADA**, 2026-11-26.

Reporte de evidencia:
[EDITOR_SYMBOL_SERVICES_ARCH_1_REPORT](EDITOR_SYMBOL_SERVICES_ARCH_1_REPORT.md).

## 1. Autoridad y alcance

Este documento define la arquitectura interna de símbolos para servicios editoriales de
`compiler-next`. La autoridad normativa es
[COMPILER_AUTHORITY](COMPILER_AUTHORITY.md): el frontend Rust y los contratos CLOSED
vigentes determinan identidad, resolución, tipos, ownership, packages, clases e interfaces.
Python, `compiler-rs` y sus LSP no son oráculos ni dependencias admisibles.

El alcance es diseñar la base común de Document Symbols, Go to Definition, Hover,
Completion y, posteriormente, Find References y Rename. No agrega handlers LSP,
capabilities, semántica, recovery, dependencias, una base incremental ni funcionalidad
productiva. MIR, SSA y detalles de backend nunca forman parte del modelo de símbolos de
usuario.

Decisiones cerradas:

1. `aether-frontend` seguirá siendo el único resolver. Emitirá hechos editoriales en los
   mismos puntos en que resuelve declaraciones, nombres, tipos y members.
2. `aether-analysis` poseerá esos hechos junto con `TypedHir`, `SourceTable` y el
   `SnapshotStamp`, y construirá índices de consulta inmutables sin reinterpretar nombres.
3. Todo ID denso (`SourceId`, `ModuleId`, `FunctionId`, `TypeId`, `LocalId`, `FieldId`,
   `InstanceId`, IDs nominales y los IDs editoriales nuevos) es local al snapshot.
4. `PackageKey`, `SourceUnitKey` y `SymbolKey` mantienen exactamente sus contratos
   oficiales. No se extiende `SymbolKey` de forma ad hoc para locales o members que hoy no
   tienen clave oficial demostrada.
5. Un resultado semántico pertenece a los bytes y versiones de un único snapshot. Nunca se
   mezcla con hechos históricos ni se publica después del gate `may_publish_analysis`.
6. Los spans continúan siendo rangos half-open en bytes UTF-8 y se convierten con el
   `SourceTable`/`LineIndex` existentes. No habrá un segundo source mapper.
7. El primer servicio productivo posterior a la instrumentación será Document Symbols.
   Rename queda explícitamente no autorizado hasta cerrar referencias verificadas y
   detección de conflictos.

## 2. Inventario real del frontend

### 2.1 Información disponible directamente (A)

| Área | Evidencia actual | Alcance real |
| --- | --- | --- |
| Texto y tokens | `SourceFile`, `SourceId`, `Span`, `Token { kind, lexeme, span }` | bytes UTF-8 exactos; los tokens no sobreviven en `ParsedAst` |
| AST | `ParsedAst`, declaraciones, statements y expressions spanned | árbol completo sólo si el parser termina; no posee identidades resueltas |
| Programa | `ParsedProgram`, `ModuleInfo`, `ResolvedImport` | módulo, package, source, imports/aliases y dependencias resueltos |
| Packages | `PackageKey`, `SourceUnitKey`, `PackageInstanceKey` | claves lógicas oficiales; separadas de IDs densos |
| Funciones | `FunctionSignature`, `FunctionId`, parámetros, genéricos, visibilidad, retorno, `symbol_key` | `SymbolKey` canónico para firmas; overload disambiguator cuando corresponde |
| Tipos | `TypeArena`, `TypeId`, `TypeData`, `StructId`, `EnumId`, `ClassId`, `InterfaceId`, `GenericParamId` | identidad y tipos canónicos dentro de la sesión |
| Aggregates | `StructInfo`, `FieldInfo`, `EnumInfo`, `VariantInfo` | owner, tipo, orden e identidad densa; spans de declaración completos |
| OOP | `ClassInfo`, `ClassFieldInfo`, `ClassMethodInfo`, `InterfaceInfo`, `RequirementInfo`, witnesses | miembros, herencia, dispatch e implementaciones resueltas |
| Locals | `HirLocal`, `HirParameter`, `LocalId`, `BindingId` | nombre, tipo, mutabilidad, parameter/source binding y declaración spanned |
| HIR | `TypedHir`, `HirFunction`, `GenericHirFunction`, `HirExpr`, `HirPlace`, `HirCallTarget` | tipos y targets concretos de calls, places, fields, variants y class operations |
| Genéricos | `GenericParamInfo`, `GenericOwner`, `FunctionInstanceInfo`, `InstanceId`, type arguments | declaración e instanciación separadas; IDs locales a sesión |
| Closures | `LambdaId`, `ClosureEnvironmentInfo`, `ClosureCaptureInfo`, `HirClosureCapture` | creator/target, binding capturado, modo, tipos y varios spans |
| Editor | `AnalysisResult`, `SemanticSnapshot`, `SourceTable`, `SnapshotSource`, `LineIndex` | snapshot, provenance y conversión UTF-8/UTF-16 coherentes |

Los scopes lexicales sí existen durante análisis (`Vec<BTreeMap<String, LocalId>>`) y se
consultan de adentro hacia afuera. Las tablas de funciones, imports, aliases, tipos y
members también existen durante collection/typing. No son hoy un API persistente del
`TypedHir` y no deben reconstruirse desde el texto.

### 2.2 Información derivable sin duplicar semántica (B)

Una vez que el frontend exponga hechos resueltos, `aether-analysis` puede derivar sin nueva
semántica:

- orden e interval tree de declaraciones/referencias por `(SourceId, Span)`;
- jerarquía documental desde las relaciones de owner emitidas por AST/frontend;
- lookup `SymbolId -> declaración`, `ReferenceId -> target` y referencias inversas;
- rangos editoriales, URI/`DocumentId` y editabilidad mediante `SourceTable`;
- display de tipos con el formatter canónico de `TypeArena`, mientras el snapshot viva;
- firma estructurada desde `FunctionSignature`, `ClassMethodInfo` o `RequirementInfo`;
- canonical target de un import alias y declaración propietaria de campos/variantes;
- visibilidad visible para un contexto cuando el frontend emita el scope y los bindings
  resueltos que ya utilizó.

Estos índices son vistas del resultado oficial. No resuelven, eligen overloads, aplican
shadowing ni buscan por spelling.

### 2.3 Información que requiere instrumentar el frontend (C)

La instrumentación mínima necesaria es:

1. conservar el span exacto del identificador de toda declaración source-facing;
2. conservar el span exacto de cada componente referenciable (callee, qualifier, type,
   method, variant y alias), no sólo el span de la expresión completa;
3. registrar, al resolver, `reference span -> CompilerEntityId` y su clase de uso;
4. registrar scopes, parent scope, declaración que introduce cada binding e intervalo
   lexical, incluidos for/catch/match/lambda;
5. registrar la relación entre métodos, overrides, virtual slots, requirements y witness
   implementations sin convertir el slot en símbolo de usuario;
6. exponer datos source-facing de clases/interfaces que hoy sólo se alcanzan a través de
   `TypeArena` y completar los spans faltantes de métodos;
7. retener artefactos de parse completo para Document Symbols cuando declarations o bodies
   fallen, sin fabricar AST parcial.

Se recomienda un `SemanticFacts` owned producido junto con el HIR, o un sink interno
equivalente alimentado por collection/typing. No se recomienda recorrer HIR después para
adivinar qué fragmento de un span originó cada identidad: varios nodos lowered pierden esa
correspondencia.

### 2.4 Información no exponible de forma segura todavía (D)

- símbolos sintácticos después del primer error de parse;
- resolución o completion semántica en texto que no produjo AST completo;
- referencias completas en un resultado semántico fallido con la API actual;
- estabilidad cross-snapshot de locales, parámetros, campos, métodos o declaraciones
  movidas, salvo una clave oficial específica;
- documentación fuente, porque no existe un modelo oficial de doc comments;
- rename seguro, hasta disponer de referencias exhaustivas y validación de colisiones;
- ubicación editable de intrinsics/Core/toolchain que no tengan source presentado;
- un símbolo de usuario para slots, witnesses, temporales, drops, captures materializados,
  MIR o SSA.

## 3. Modelo de identidades

### 3.1 Dominios separados

```rust
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SymbolId(u32);       // sólo dentro de SymbolSnapshot

#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ReferenceId(u32);    // sólo dentro de SymbolSnapshot

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum CompilerEntityId {
    Module(ModuleId),
    Function(FunctionId),
    Local { function: FunctionId, binding: BindingId },
    Struct(StructId),
    StructField(FieldId),
    Enum(EnumId),
    EnumVariant(VariantId),
    Class(ClassId),
    ClassField(FieldId),
    Interface(InterfaceId),
    Requirement(RequirementId),
    GenericParameter(GenericParamId),
    ImportBinding { module: ModuleId, ordinal: u32 },
    TypeAlias { module: ModuleId, ordinal: u32 },
    Lambda { creator: FunctionId, source: LambdaId },
    Builtin(CoreSymbolKey),
}

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub enum LogicalSymbolKey {
    PackageMember(SymbolKey),
    SourceUnit(SourceUnitKey),
}

pub struct GenericInstanceIdentity {
    pub declaration: SymbolId,
    pub compiler_instance: InstanceId,
    pub type_arguments: Box<[TypeId]>,
}
```

`CompilerEntityId` no es persistente: sólo une hechos del mismo frontend run. El enum es
orientativo y debe ajustarse a las identidades oficiales disponibles al implementar; no
autoriza reinterpretar el `FieldId` compartido por distintas tablas sin su variante owner.

`LogicalSymbolKey` sólo se asigna cuando una clave oficial expresa realmente esa identidad.
No se fabrica para un local a partir de nombre+offset. `SymbolKey` continúa siendo
package/member y conserva el disambiguador de overload que entrega `FunctionSignature`.
Los tipos/members que aún no exponen una clave lógica oficial siguen siendo snapshot-local.

### 3.2 Declaración, definición, referencia e instancia

- Un `SymbolId` identifica una declaración source-facing dentro de un `SymbolSnapshot`.
- La definición es la ubicación primaria de esa declaración. V1 no distingue forward
  declaration porque el lenguaje actual no la expone; el modelo permite ubicación ausente.
- Un `ReferenceId` identifica una ocurrencia source y apunta a cero, uno o varios
  `SymbolId` según el resultado oficial.
- Una instancia genérica no crea por defecto otro símbolo documental: es una realización
  snapshot-local de la declaración con `InstanceId` y argumentos exactos.
- `SourceId` identifica provenance del span; `SourceIdentity`/`DocumentId` presentan el
  source; `SourceUnitKey` identifica la unidad lógica; ninguno sustituye a los otros.

### 3.3 Estabilidad y cambios

| Caso | Contrato |
| --- | --- |
| Shadowing | dos `SymbolId`; cada referencia conserva el target elegido por el scope oficial |
| Overloads | símbolos distintos por declaración/disambiguador; una referencia puede ser `Ambiguous` antes de selección |
| Import alias | símbolo local del binding más `canonical_target`; renombrarlo no renombra el target |
| Rename global | cambia spelling y normalmente `SymbolKey`; no se promete conservar identidad lógica |
| Declaración movida | dentro del mismo package un `SymbolKey` oficial puede coincidir, pero provenance cambia; fuera del package no |
| Función/local/parameter | `FunctionId`/`BindingId` sólo dentro del snapshot; sin promesa cross-snapshot |
| Field/method/variant | owner + ID denso dentro del snapshot; clave estable futura requiere contrato propio |
| Sintético | `SymbolOrigin::Generated`; sin ubicación editable y oculto por defecto |
| Instancia genérica | identidad `(declaration, exact type arguments)` sólo dentro de la arena/snapshot |

No se usa similitud de texto, posición relativa, traversal order ni nombre solo para afirmar
que dos símbolos de snapshots diferentes son el mismo. Un cache conserva la sesión completa
o reindexa el nuevo snapshot.

## 4. Source mapping

```rust
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SymbolLocation {
    pub source: SourceIdentity,
    pub document: Option<DocumentId>,
    pub source_unit: Option<SourceUnitKey>,
    pub full_span: Span,
    pub selection_span: Span,
    pub editable: bool,
}
```

`full_span` cubre la declaración/referencia completa según su nodo source; `selection_span`
cubre exclusivamente el identificador. Ambos deben tener el mismo `SourceId`, ser half-open,
estar dentro del texto exacto del `SnapshotSource` y caer en boundaries UTF-8. Un símbolo sin
source usa `location: None`; no recibe un span cero ficticio.

La recuperación es siempre:

1. `Span.source -> SourceTable::get(SourceId)` del mismo `SemanticSnapshot`;
2. `SnapshotSource::{identity, document_version, unit, text}`;
3. `LineIndex::span_to_range` para UTF-16;
4. URI sólo en el adaptador protocolar, usando las reglas existentes para Document/Disk.

`ModuleInfo.source` da el source de una entidad cuyo `module` es conocido. Para fields,
variants, methods y requirements se sigue primero su owner hasta el módulo. El span sigue
siendo autoridad y debe concordar con ese source; una discrepancia es un fallo interno. La
ubicación de un módulo importado se obtiene desde su `ResolvedImport.module`, luego
`ModuleInfo.source`, nunca desde el spelling del import.

El source del tipo asociado se ofrece sólo para tipos nominales o parámetros genéricos con
declaración: `TypeId` se clasifica en `TypeArena`, se sigue su ID nominal/owner hasta el
módulo y de allí al `SourceTable`. Primitivos, tipos estructurales, Core e instancias no
reciben una ubicación inventada; una instancia enlaza a la declaración nominal y conserva
sus argumentos por separado.

La instrumentación debe agregar `name_span` a declarations que hoy sólo conservan el span
completo. No se permite recortar el texto buscando el nombre: comentarios, Unicode,
calificadores y nombres repetidos lo vuelven ambiguo.

## 5. Tipos y APIs Rust

Los nombres definitivos priorizan el dominio editorial y evitan confundir `SymbolId` con
`SymbolKey`:

```rust
pub enum SymbolKind {
    Package, Module, Import, TypeAlias,
    Function, Method, Constructor,
    Parameter, Variable, TypeParameter,
    Struct, StructField, Enum, EnumVariant,
    Class, ClassField, Interface, InterfaceRequirement,
    Lambda,
}

pub enum SymbolVisibility {
    Public,
    Package,
    Private,
    Lexical,
    NotApplicable,
}

pub enum SymbolOrigin {
    Source,
    Toolchain,
    Core,
    Generated { reason: GeneratedSymbolReason },
}

pub struct SymbolDeclaration {
    pub id: SymbolId,
    pub entity: CompilerEntityId,
    pub logical: Option<LogicalSymbolKey>,
    pub name: Arc<str>,
    pub kind: SymbolKind,
    pub owner: Option<SymbolId>,
    pub visibility: SymbolVisibility,
    pub origin: SymbolOrigin,
    pub location: Option<SymbolLocation>,
    pub ty: SymbolType,
    pub signature: Option<SymbolSignature>,
}

pub enum SymbolType {
    Known(TypeId),
    Declaration { nominal: TypeId },
    Unavailable(SymbolUnavailableReason),
}

pub struct SymbolSignature {
    pub parameters: Box<[SignatureParameter]>,
    pub result: Option<TypeId>,
    pub type_parameters: Box<[SymbolId]>,
    pub receiver: Option<TypeId>,
}

pub struct SymbolReference {
    pub id: ReferenceId,
    pub spelling: Arc<str>,
    pub kind: ReferenceKind,
    pub location: SymbolLocation,
    pub resolution: ReferenceResolution,
}

pub enum ReferenceResolution {
    Resolved(SymbolId),
    Ambiguous(Box<[SymbolId]>),
    Unresolved,
    Unavailable(SymbolUnavailableReason),
}

pub struct ResolvedSymbol<'a> {
    pub declaration: &'a SymbolDeclaration,
    pub via_alias: Option<&'a SymbolDeclaration>,
    pub instance: Option<&'a GenericInstanceIdentity>,
}
```

`Unavailable` no inventa un tipo `Unknown`; explica que la fase no produjo el hecho. Las
firmas son datos semánticos estructurados. Markdown, labels LSP y documentación se generan
fuera del modelo. Un symbol Core/toolchain puede ser resoluble y no navegable.

```rust
pub struct SymbolSnapshot {
    stamp: SnapshotStamp,
    sources: Arc<SourceTable>,
    facts: Arc<SemanticFacts>,
    declarations: Box<[SymbolDeclaration]>,
    references: Box<[SymbolReference]>,
    scopes: Box<[ScopeInfo]>,
    // índices derivados por source/span/id
}

impl SymbolSnapshot {
    pub fn symbol_at(&self, source: SourceId, byte: usize) -> SymbolAtResult<'_>;
    pub fn definition_at(&self, source: SourceId, byte: usize) -> DefinitionResult<'_>;
    pub fn document_symbols(&self, source: SourceId) -> DocumentSymbolResult<'_>;
    pub fn hover_facts(&self, source: SourceId, byte: usize) -> HoverFactsResult<'_>;
    pub fn visible_symbols(&self, source: SourceId, byte: usize) -> VisibleSymbolsResult<'_>;
    pub fn references_to(&self, symbol: SymbolId) -> ReferencesResult<'_>;
}
```

Toda consulta valida que source y posición pertenecen al snapshot. Empates de spans se
resuelven por selección exacta y nesting, no por nombre; si los hechos oficiales no permiten
decidir se devuelve ambigüedad.

## 6. Scopes y resolución

```rust
pub struct ScopeId(u32);

pub struct ScopeInfo {
    pub id: ScopeId,
    pub parent: Option<ScopeId>,
    pub owner: Option<SymbolId>,
    pub source: SourceId,
    pub span: Span,
    pub bindings: Box<[ScopeBinding]>,
}

pub struct ScopeBinding {
    pub name: Arc<str>,
    pub symbol: SymbolId,
    pub introduced_at: usize,
    pub namespace: BindingNamespace,
}
```

El frontend ya aplica estas reglas y la API sólo debe exponer su resultado:

- locales, parámetros, for/catch/match bindings y captures: scope lexical más interno;
- funciones: tablas package/module, visibilidad y overload selection oficiales;
- imports: bindings de namespace por source unit; alias no cambia target canónico;
- structs/enums/aliases/classes/interfaces: resolución nominal por módulo/package;
- fields: tipo exacto del receiver y `FieldId`/class field elegido;
- methods: clase efectiva, override/virtual slot o requirement/witness ya elegidos;
- genéricos: `GenericParamId`, constraints y substitutions oficiales;
- closures: `BindingId` del creator, capture mode y target de lambda.

`visible_symbols` no vuelve a correr precedencia. Consume una fotografía de bindings de
scope producida por el resolver, filtrada por posición (`introduced_at`) y namespace. Para
completion de members consume candidatos que el frontend pueda enumerar para el receiver
resuelto. Si esa API no existe, la respuesta queda `Unavailable`; no se escanean tablas por
nombre desde analysis.

## 7. Document Symbols

Es el primer servicio productivo porque puede separar claramente hechos sintácticos de
hechos semánticos.

Incluye declarations source-facing del source solicitado: package/module cuando resulte
útil, imports y aliases, type aliases, structs/fields, enums/variants, classes/fields/methods/
initializer, interfaces/requirements, funciones, type parameters, parámetros y opcionalmente
locales nombrados. La primera versión debe limitarse a declaraciones estructurales y puede
incorporar locals en un milestone posterior para evitar ruido.

Jerarquía:

- source → aggregate/function/interface;
- aggregate → type parameters, fields, variants o methods;
- function/method → type parameters y parámetros;
- declaraciones lexicales → owner lexical si se habilitan;
- lambdas sintéticas no aparecen salvo opción interna de depuración.

`range` usa `full_span`; `selectionRange` usa `selection_span` y debe estar contenido en el
primero. El mapping a `DocumentSymbolKind` LSP ocurre en `aether-lsp`, no en el modelo.
Imports pueden aparecer como `Namespace`/`Module` en protocolo, pero conservan
`SymbolKind::Import` internamente. Visibilidad se conserva como metadata aunque LSP no tenga
campo directo.

Con parse completo, las declaraciones y jerarquía provienen del AST retenido; semántica
enriquece identidad, tipo y firma. Frente a error semántico, puede devolverse una vista
syntax-only marcada `Partial` si corresponde exactamente al AST completo actual. Frente a
error léxico o sintáctico no hay AST parcial actual: se devuelve `Unavailable`, no símbolos
del prefijo ni del snapshot anterior.

## 8. Go to Definition

```rust
pub enum DefinitionResult<'a> {
    Resolved(ResolvedSymbol<'a>),
    Unresolved,
    Ambiguous(Box<[ResolvedSymbol<'a>]>),
    Unavailable(DefinitionUnavailableReason),
}
```

`definition_at(source, position)` convierte UTF-16 a byte con el `LineIndex` del snapshot,
elige la referencia cuyo `selection_span` contiene el byte y sigue su identidad resuelta.
Casos:

- local/parameter/capture → binding declaration exacta, respetando shadowing;
- function/method → declaration seleccionada, no todas las del mismo nombre;
- imported member → declaración canónica cross-file; qualifier/alias puede devolver el
  binding local y su `canonical_target` como cadena explícita;
- field/variant/type nominal/generic parameter → owner declaration exacta;
- instancia genérica → definición de la declaración, con instance metadata separada;
- toolchain/Core → `Resolved` con location cuando exista, o `Unavailable(NotNavigable)`;
- declaración bajo cursor → puede resolverse a sí misma.

No existe fallback por igualdad textual. Una referencia que el frontend marcó unresolved
permanece `Unresolved`; overload no seleccionado es `Ambiguous`; falta de hechos por fase,
snapshot no publicable o source sin mapping es `Unavailable`.

## 9. Hover

Hover consume `ResolvedSymbol` y produce hechos, no Markdown:

```rust
pub struct HoverFacts {
    pub name: Arc<str>,
    pub kind: SymbolKind,
    pub ty: SymbolType,
    pub signature: Option<SymbolSignature>,
    pub visibility: SymbolVisibility,
    pub owner_name: Option<Arc<str>>,
    pub package: Option<PackageKey>,
    pub source_unit: Option<SourceUnitKey>,
    pub generic_instance: Option<GenericInstanceIdentity>,
    pub documentation: DocumentationFacts,
}
```

Tipos se formatean desde `TypeArena`; parámetros/retorno desde firmas oficiales; clase,
interfaz y módulo desde owners resueltos. `DocumentationFacts::Unavailable` es el único valor
actual: no se infiere documentación de comentarios comunes ni se inventa texto. El adaptador
LSP decide code fences y Markdown, sin alterar hechos.

Hoy faltan referencias completas y spans de selección para hover fiable sobre calls,
methods, types e imports. También falta un contrato de doc comments. Por ello Hover depende
de SYMBOL-RESOLUTION-QUERIES-V1 y no puede implementarse sólo recorriendo HIR.

## 10. Completion

Completion se divide en:

- **semántica:** bindings visibles, funciones/tipos nominales, imports, fields, methods,
  genéricos, Core/stdlib y expected type, todos entregados por frontend;
- **sintáctica:** keywords y formas permitidas según contexto parser;
- **léxica:** fragmento identificador para reemplazo, sin autoridad de resolución.

La API futura recibe snapshot, posición y `CompletionContext`; devuelve candidatos con
`SymbolId`/identidad de builtin, clase de candidato, tipo/firma y razón de disponibilidad.
Orden, snippets y presentación son capa protocolar.

HIR completo cubre únicamente sources válidos y no basta para edición incompleta. Se
necesitan milestones separados de parser recovery/context detection que entreguen un nodo o
estado sintáctico autoritativo, además de scopes parciales oficialmente emitidos. Hasta
entonces:

- en snapshot completo actual se admite completion semántica en posiciones mapeables;
- en source inválido sólo se admiten keywords u otras sugerencias sintácticas si un parser
  oficial puede demostrar el contexto;
- no se usa HIR histórico como si correspondiera al texto actual;
- no se agregan members por regex, prefix scan global o parsing alternativo.

Expected type debe provenir del typechecker en un punto instrumentado. Builtins/Core y std
se enumeran mediante sus manifests/tablas canónicas y grants reales, no mediante listas
duplicadas en el LSP.

## 11. Find References y Rename

`references_to(SymbolId)` usa el reverse index de `SymbolReference.resolution`, limitado al
grafo exacto analizado. El resultado declara cobertura (`Document`, `ProjectGraph` o
`Incomplete`) y distingue reads, writes, calls, type uses, imports, captures y declarations.
Igual spelling nunca es evidencia.

Rename requiere adicionalmente:

1. `Complete + Valid` vigente para todo el project graph afectado;
2. cobertura exhaustiva de referencias para ese símbolo y aliases tratados según intención;
3. scopes y namespaces para simular el nuevo binding con el resolver oficial;
4. detección de shadowing, colisiones, overloads, visibilidad y conflicts cross-file;
5. spans editables en documentos/versiones del mismo snapshot;
6. `WorkspaceEdit` versionado y revalidación inmediatamente antes de aplicar;
7. política explícita para package member, import alias, method/override/requirement y
   toolchain.

No se autoriza Rename cuando haya referencias `Unresolved`/`Unavailable`, sources no
editables, análisis parcial/stale o ausencia de una API oficial de validación del nuevo
nombre. V1 de references será read-only; Rename es el último milestone.

## 12. Recovery y análisis parcial

| Estado actual | Document Symbols | Definition/Hover | Completion | References/Rename |
| --- | --- | --- | --- | --- |
| `Complete + Valid` vigente | completo | habilitado | semántico donde haya contexto | references según cobertura; rename aún gated |
| error semántico con AST completo retenido | syntax-only, `Partial` | sólo hechos oficialmente resueltos y conservados; inicialmente unavailable | sintáctico oficial únicamente | unavailable |
| error de declarations | syntax-only si el AST exacto se retiene | unavailable | sintáctico oficial únicamente | unavailable |
| error léxico/sintáctico fail-fast | unavailable con parser actual | unavailable | unavailable salvo recovery futuro | unavailable |
| cancelled/internal | no publicar | no publicar | no publicar | no publicar |
| snapshot stale | no presentar como actual | no presentar como actual | no presentar como actual | prohibido |

Un `HistoricalSemantic` puede conservarse internamente para latencia o UI explícitamente
degradada, pero debe mostrar su `based_on` y nunca responder Definition/Rename para la
versión actual. No se combinan declarations nuevas con referencias antiguas. No se fabrican
nodos AST/HIR ni símbolos placeholders.

## 13. Dependencias y límites de crates

La implementación vive en un módulo nuevo `aether_analysis::symbols` porque:

- consume `SemanticSnapshot`, `SourceTable`, snapshots, documentos y lifecycle;
- es una vista editorial, no semántica del lenguaje;
- permite que futuros consumidores distintos de LSP reutilicen las consultas;
- no justifica todavía otro crate ni un framework incremental.

La instrumentación y tipos de hechos de resolución mínimos viven en `aether-frontend` porque
sólo allí existe el contexto autoritativo. `aether-analysis` adapta esos hechos a símbolos y
los posee con la sesión. `aether-lsp` sólo convierte posiciones/resultados al protocolo.

Dirección:

```text
aether-package -> aether-frontend (resuelve y emite SemanticFacts)
                         |
                         v
                 aether-analysis::symbols (índices/queries snapshot-local)
                         |
                         v
                    aether-lsp (adaptador futuro)
```

La capa no depende de `aether-driver`, `aether-middle`, `aether-backend-llvm`, LLVM,
toolchain nativo, Python ni `compiler-rs`. No se agrega una base persistente de símbolos ni
se copian tablas del resolver.

## 14. Plan incremental

1. **SYMBOL-SOURCE-MAPPING-V1** — primer milestone recomendado. Agregar `name_span` exacto
   a declaraciones/componentes referenciables, validar owner/source, definir
   `SemanticFacts` y probar que su emisión no cambia HIR ni semántica. Sin handlers.
2. **DOCUMENT-SYMBOLS-V1** — retener AST completo del snapshot, crear declaraciones y
   jerarquía, vista syntax-only explícita ante fallo semántico y API interna.
3. **SYMBOL-RESOLUTION-QUERIES-V1** — emitir identities de referencias y scopes desde el
   resolver; índices `symbol_at`, alias chain y reverse references básicos.
4. **GO-TO-DEFINITION-V1** — consulta cross-file completa, toolchain no editable y
   adaptación LSP/capability en un milestone protocolar acotado.
5. **HOVER-V1** — facts de tipo/firma/owner y renderer separado.
6. **COMPLETION-CONTEXT-RECOVERY-V1** — context detection/parser recovery oficial; no
   presupone semántica completa.
7. **COMPLETION-V1** — scopes, members, imports, Core/std y expected type.
8. **REFERENCES-V1** — reverse index con cobertura explícita del project graph.
9. **RENAME-VALIDATION-V1** — API frontend para validar nuevo binding y conflictos.
10. **RENAME-V1** — edits versionados cross-file; sólo después de todos los gates.

La separación evita que Document Symbols quede bloqueado por completion/recovery y evita
autorizar rename con un índice incompleto.

## 15. Qualification

Cada milestone debe separar tests de frontend, API editorial y protocolo LSP.

| Área | Gates mínimos |
| --- | --- |
| Identidad | IDs no comparables entre snapshots; `SymbolKey` oficial preservado; nombres iguales y shadowing no colisionan; overloads separados |
| Spans | full/name/reference exactos; owner/source concordante; ASCII, acentos, CJK, combining, emoji, LF/CRLF y EOF |
| Scopes | nested blocks, declaration order, parameters, for/catch/match, shadowing y captures |
| Modules/packages | anonymous/named, imports transitivos, aliases, multi-package y toolchain no suplantable |
| Declarations | functions, locals, parameters, aliases, structs/fields, enums/variants, classes/methods, interfaces/requirements y generics |
| Resolución | read/write/call/type/member/method/variant, override/dispatch, generic instance y unresolved/ambiguous |
| Cross-file | definition y references conservan `SourceIdentity`, overlay importado no guardado y URI correcta |
| Lifecycle | edición rápida, cancellation, stale, close, source changed y version gate |
| Partial | lex/parse/declaration/semantic diferenciados; no AST parcial inventado ni HIR histórico presentado como actual |
| Determinismo | mismos inputs en distinto orden producen los mismos hechos lógicos y orden de resultados |
| Frontera | `cargo tree` sin driver/middle/backend/legacy; ningún regex/name resolver paralelo |

Gates específicos:

- SYMBOL-SOURCE-MAPPING-V1: cada fact referencia un source de la tabla; selection está
  contenido en full; round-trip UTF-16; corrupción se rechaza; HIR dumps/tests oficiales no
  cambian salvo metadata intencional.
- DOCUMENT-SYMBOLS-V1: jerarquía/rangos/kinds deterministas; syntactic-only etiquetado;
  ningún sintético interno publicado.
- RESOLUTION/DEFINITION: cada referencia válida apunta a la declaración que el frontend
  eligió; tests negativos prueban que spelling igual no alcanza.
- REFERENCES: cobertura declarada y conjunto inverso exacto, incluidos aliases/captures.
- RENAME: rechaza conflictos, partial, stale, no editable e incomplete coverage antes de
  producir un solo edit.

Qualification común: `cargo test -p aether-frontend`, `cargo test -p aether-analysis`, tests
LSP sólo cuando exista adaptador, `cargo check --workspace`, fmt, clippy, diferencial oficial,
`git diff --check` y revisión de dependencias. Los tests editoriales no invocan legacy.

## 16. Riesgos y limitaciones

| Riesgo | Contención |
| --- | --- |
| reconstruir resolución desde HIR/texto | facts emitidos en el punto autoritativo del frontend |
| confundir IDs densos con persistentes | ownership por `SymbolSnapshot`; sólo claves lógicas oficiales cruzan snapshots |
| spans de identifier ausentes | primer milestone dedicado; nunca búsqueda textual |
| HIR lowering pierde source intent | capturar reference facts durante typing antes de perderlo |
| overload/dispatch mal atribuido | registrar target seleccionado, slot/requirement sólo como metadata |
| stale u overlay incorrecto | mismo `SnapshotStamp`, `SourceTable` y publication gate existentes |
| parser fail-fast limita servicios | estados `Unavailable/Partial`; recovery separado |
| índices consumen memoria | estructuras owned por snapshot y liberadas con él; medir antes de granularidad incremental |
| rename corruptor | no autorizar hasta references y conflict validation completos |
| API congela internals | tipos internos de `aether-analysis`; sin ABI pública de HIR |

Limitaciones aceptadas: no hay estabilidad general cross-snapshot, doc comments, recovery
sintáctico, completion sobre texto roto, references exhaustivas ni rename. El diseño es
implementable incrementalmente sin alterar semántica ni agregar dependencias.

## 17. Decisión de cierre

`EDITOR-SYMBOL-SERVICES-ARCH-1` queda **ARCH CLOSED**. Las identidades no dependen de IDs
persistentes ficticios; la resolución sigue siendo exclusiva del frontend; source mapping y
lifecycle reutilizan la infraestructura vigente; las ausencias de spans/references/recovery
se convierten en milestones explícitos; y el primer cambio recomendado está acotado a
instrumentación source-facing. Este cierre no inicia automáticamente implementación alguna.
