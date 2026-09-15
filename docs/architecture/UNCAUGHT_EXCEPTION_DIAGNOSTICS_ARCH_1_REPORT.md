# UNCAUGHT-EXCEPTION-DIAGNOSTICS-ARCH-1 — reporte

Estado: **ARQUITECTURA CERRADA; SIN IMPLEMENTACIÓN**, 2026-09-15.

Documento normativo:
[UNCAUGHT_EXCEPTION_DIAGNOSTICS_ARCH_1](UNCAUGHT_EXCEPTION_DIAGNOSTICS_ARCH_1.md).

## Resultado

Se cerró el diagnóstico V1 para una excepción Aether que escapa del entrypoint:

```text
Unhandled <tipo-nominal-dinámico>\n
```

La línea va exclusivamente a stderr y el proceso termina con status estable 70.
No se agregan stack traces, locations, messages, causes, formatting general ni
reflection.

El tipo se obtiene del class descriptor guardado en el objeto lanzado. Upcast,
propagación, catch y rethrow preservan ese descriptor, por lo que una instancia
concreta conserva su identidad aunque el owner estático sea `Exception` o una
base intermedia.

## Boundary y lifecycle

El boundary elegido es el landing pad root ya generado en el wrapper nativo
`main`, sobre el unwind edge del `invoke` al `main` Aether. Los frames Aether ya
completaron sus cleanups y `finally` antes de llegar allí. Traps, señales y
foreign exceptions no pertenecen a esta ruta.

El record EH posee el payload. El root toma sólo un borrow para reportar, escribe
mientras el objeto está vivo y después finaliza una vez el catch/evento. El
destructor vigente del record libera el payload. No se agrega un release manual,
evitando double-drop, ni se omite el fin de catch, evitando leaks.

## Naming cerrado

| Caso | Display |
| --- | --- |
| package nombrado `A.B`, clase `E` | `A.B.E` |
| anonymous package, clase `E` | `E` |
| excepción STD | `std.IO.E`, `std.File.E`, etc. |
| Core compiler-owned | `Exception` |

La autoridad es `PackageKey` más la identidad de clase. No se usan
`ModuleInfo.display_name`, mangling, source path, logical source, CWD ni labels
internos. El origin Project/Toolchain no se imprime porque no es sintaxis
source-facing. Las clases actuales son top-level; nesting nominal futuro deberá
agregar enclosing identities semánticas, nunca inferirlas del símbolo físico.

## Metadata mínima

La auditoría confirmó que el objeto actual ya lleva el descriptor concreto,
pero el descriptor LLVM sólo contiene destroy y slots de dispatch/witness. El
nombre existe en compile time (`ClassInfo.module/name` y
`ModuleInfo.key.package`), no como metadata runtime uniforme.

Se decidió agregar al prefijo común del descriptor un único puntero a una record
estática privada `{bytes, byte_length}`. Esto agrega cero bytes por objeto y
cero trabajo al path ordinario. La string sirve sólo para presentación: no
participa en matching, identidad, casts ni dispatch y no es reflection pública.
Los offsets de virtual slots y witnesses deberán centralizarse y ajustarse en el
vertical, ya que el class ABI actual es privado.

Se descartó un switch cerrado descriptor→literal dentro del reporter porque
duplicaría conocimiento de identidad ya propio del descriptor. También se
descartó copiar ClassId/nombre al `ExceptionEvent`, lo cual introduciría una
segunda autoridad susceptible de divergir del payload.

## Failure path

El reporter usa slices estáticos y una primitive privada non-throwing de
`write_all` sobre fd 2. No crea strings Aether, no formatea y no asigna memoria;
por tanto no puede lanzar ni sufrir OOM propio. Short writes se completan,
`EINTR` se reintenta y un error terminal abandona el output restante. Aun con
stderr fallido, el event se dispone y se retorna 70; no hay fallback a stdout ni
exception recursiva.

Payload/descriptor/metadata corruptos siguen siendo runtime invariant traps. El
root no captura traps ni promete recuperación después de corrupción.

## Primer vertical

**UNCAUGHT-EXCEPTION-DIAGNOSTICS-V1 — concrete nominal root report** debe:

1. construir displays canónicos desde identidad semántica;
2. ampliar descriptor y emitir metadata/literals estáticos;
3. hacer el reporter dinámico, length-aware, allocation-free y `nounwind`;
4. preservar report → end-event → status 70;
5. calificar named, anonymous, STD, derived, caught, rethrow, finally, canales,
   lifecycle, fallos de stderr y O0/O2.

## Validación de este milestone

- Se crearon únicamente el documento normativo y este reporte.
- No se modificó compiler-next, runtime, stdlib, tests ni compiler legacy.
- Se preservó el cambio preexistente en `examples/word_stats/main.ae`.
- Quedaron cerrados boundary, tipo dinámico, naming, metadata, stderr, LF,
  status 70, ownership, anonymous package y fallos del reporter.
- Las decisiones abiertas corresponden a features posteriores y no bloquean el
  vertical V1.

