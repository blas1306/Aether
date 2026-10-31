# PLOTS-2D-LINE-V1 — reporte de implementación y qualification

Estado: **BLOQUEADO EN PREFLIGHT; NO IMPLEMENTADO**, 2026-10-30.

Documento normativo: [PLOTS-ARCH-1](PLOTS_ARCH_1.md).

## Resultado

El preflight encontró un bloqueo real del lenguaje antes de crear código
productivo: Aether no admite actualmente un field `string` owning dentro de
una class. La representación normativa de `Figure2D` exige tres strings owning
(`title`, `xLabel`, `yLabel`) para que la figura sea inmutable e independiente
de `FigureOptions`. El frontend rechaza el caso mínimo con `E0401`:

```text
class Figure2D {
    string title;
    public init(string ownedTitle) { title = ownedTitle; }
}
```

```text
error[E0401] (semantic): class field requires a scalar/Copy value, an admitted
private Buffer<E>, or a private non-self concrete class owner
```

Esto coincide con el límite todavía declarado por
`GENERAL_V2_STRING_COMPOSITION_REPORT.md`: “fields class string” permanece
fuera de alcance. Por tanto, la afirmación de capability en PLOTS-ARCH-1 §5 y
§20 no está implementada en el lenguaje vigente.

No se modificaron compiler, runtime, Core, std, Graphics, SVG, Plots legacy ni
ejemplos. No se creó un `plots` productivo parcial porque omitir, prestar o
descartar los textos rompería ownership, inmutabilidad y la superficie pública
normativa. No se hizo commit ni push.

## Reproducers de preflight

- `reproducers/plots_preflight`: reproducer mínimo negativo del field `string`
  owning en `Figure2D`.
- `reproducers/plots_preflight_positive`: control positivo que prueba
  `Buffer<DataPoint>` privado, copia desde `ref Array<DataPoint>`, recorrido en
  método read, alias ARC, mutation-after-call, `ref Figure2D`, `scene()`, e
  imports y delegación a `graphics.svg.render`.
- `reproducers/plots_transform_preflight.ae`: estabilidad y límites de la
  transformación normativa de §10.

El control positivo pasó `check`, `build` y `run` en O0 y O2. El reproducer
negativo falla determinísticamente en análisis semántico con `E0401`, antes de
HIR ejecutable o lowering.

## Estabilidad numérica de §10

Se mantuvo y probó el orden normativo:

```text
sx = W / (xmax - xmin)
sy = H / (ymax - ymin)
xv = L + (x - xmin) * sx
yv = T + H - (y - ymin) * sy
```

Resultados concretos O0/O2:

- domains ordinarios preservan exactamente los cuatro anchors;
- un span subnormal positivo puede hacer overflow en `W / span`, por lo que la
  transformación debe producir `PlotRangeException` al integrarse;
- un sample finito muy alejado de explicit limits puede desbordar `x - xmin`
  antes del clipping y también debe producir `PlotRangeException`;
- un domain grande con span finito representable continúa transformándose con
  resultados finitos.

Estos límites ya están exigidos explícitamente por §10. No se propone cambiar
el orden de operaciones y, por ello, no se añadió una enmienda normativa.

## Impacto sobre el vertical

El bloqueo afecta la construcción y publicación de `Figure2D`, y por
dependencia impide implementar con fidelidad `line`, `scene`, `plots.svg`, los
goldens y la matriz integral de §19. Las partes no afectadas fueron aisladas y
probadas por el control positivo, pero no constituyen un package productivo.

Para reanudar el vertical hace falta cerrar primero una capability general de
fields `string` owning en classes, con init, alias ARC de la class, drop normal,
unwind y replacement interno correctamente calificados. PLOTS no debe resolver
esa carencia mediante intrinsic, allowlist, estado global, borrow retenido o
wrapper especial.

## Gates

| Gate | Resultado |
|---|---|
| preflight positivo `check/build/run -O0` | PASS |
| preflight positivo `check/build/run -O2` | PASS |
| transformación `check/build/run -O0` | PASS |
| transformación `check/build/run -O2` | PASS |
| field `string` owning de Figure | BLOCKED — `E0401` |
| package productivo `plots` / `plots.svg` | NOT RUN — depende del bloqueo |
| qualification §19 y goldens | NOT RUN — depende del bloqueo |
| declaración `PLOTS-2D-LINE-V1 CLOSED` | NO |

**Estado final: BLOCKED BY CLASS STRING FIELDS.**
