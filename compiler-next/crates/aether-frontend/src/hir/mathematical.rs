//! Compile-time native multiplication table and mathematical scalar recipes.
//!
//! The resolved HIR variants are the closed semantic classification: scaling
//! retains its scalar side/rank, and `AlgebraicProduct` retains its result recipe.
//! There is no second dispatch tag or runtime operator protocol. Known shape
//! facts remain in `OwnershipAnalysis`, where descriptor provenance is available.
use super::{
    AlgebraicCapability, AlgebraicProductKind, Analyzer, BehavioralCapability, Capability, Checked,
    Diagnostic, DiagnosticCategory, FloatType, FloatValue, HirBinaryOp, HirExpr, HirExprKind,
    MathElementOp, MathShapeCheck, MatrixProductExtent, Phase, ScalarSide, Span, TypeArena,
    TypeData, TypeId, VerificationSignatures, format_type,
};

impl Analyzer<'_> {
    /// Resolve the complete native mathematical `*` table after literal typing
    /// and readable operand capture. At least one operand is mathematical.
    /// Exact type/capability checks deliberately retain their diagnostic order.
    ///
    /// Row × Column -> T; Column × Row -> Matrix; Matrix × Column -> Column;
    /// Row × Matrix -> Row; Matrix × Matrix -> Matrix. Exactly one mathematical
    /// operand selects scaling on either side. All other mathematical pairings
    /// fail closed, even when a runtime dimension happens to be one.
    /// The returned typed HIR node is the closed semantic resolution result.
    pub(super) fn resolve_native_multiplication(
        &mut self,
        l: Checked,
        r: Checked,
        span: Span,
    ) -> Result<Checked, Vec<Diagnostic>> {
        let lv = self.types.vector_like_info(l.expr.ty);
        let rv = self.types.vector_like_info(r.expr.ty);
        let lm = self.types.matrix_like_element(l.expr.ty);
        let rm = self.types.matrix_like_element(r.expr.ty);
        let error = |code, reason: &str| {
            vec![Diagnostic::new(
                code,
                Phase::Semantic,
                DiagnosticCategory::Type,
                format!(
                    "operator * on {} and {}: {reason}",
                    self.type_name(l.expr.ty),
                    self.type_name(r.expr.ty)
                ),
                Some(span),
            )]
        };
        if let (Some((element, lo)), Some((re, ro))) = (lv, rv) {
            if lo == ro {
                return Err(error(
                    "E0342",
                    "algebraic Vector multiplication requires Row × Column or Column × Row",
                ));
            }
            if element != re {
                return Err(error(
                    "E0343",
                    "algebraic multiplication requires identical canonical element types",
                ));
            }
            let inner = lo == crate::types::Orientation::Row;
            let (product_op, product) = vector_product_recipe(self.types, element, inner, span)
                .map_err(|reason| error("E0346", &reason))?;
            self.types.intern_vector_view(element, lo, false);
            self.types.intern_vector_view(element, ro, false);
            let ty = if inner {
                element
            } else {
                self.types.intern_matrix(element)
            };
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::AlgebraicProduct {
                        left: Box::new(l.expr),
                        right: Box::new(r.expr),
                        element_type: element,
                        product_op,
                        product,
                    },
                    ty,
                    span,
                },
                constant: None,
            });
        }
        if let (Some(element), Some(right_element)) = (lm, rm) {
            if element != right_element {
                return Err(error(
                    "E0343",
                    "algebraic multiplication requires identical canonical element types",
                ));
            }
            let (product_op, product) = matrix_matrix_recipe(self.types, element, span)
                .map_err(|reason| error("E0346", &reason))?;
            self.types.intern_matrix_view(element, false);
            let ty = self.types.intern_matrix(element);
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::AlgebraicProduct {
                        left: Box::new(l.expr),
                        right: Box::new(r.expr),
                        element_type: element,
                        product_op,
                        product,
                    },
                    ty,
                    span,
                },
                constant: None,
            });
        }
        let matrix_pair = match (lm, rv, lv, rm) {
            (Some(e), Some((v, crate::types::Orientation::Column)), _, _) => {
                Some((e, v, ScalarSide::Left))
            }
            (_, _, Some((v, crate::types::Orientation::Row)), Some(e)) => {
                Some((e, v, ScalarSide::Right))
            }
            _ => None,
        };
        if let Some((element, vector_element, side)) = matrix_pair {
            if element != vector_element {
                return Err(error(
                    "E0343",
                    "algebraic multiplication requires identical canonical element types",
                ));
            }
            let (product_op, product) = matrix_vector_recipe(self.types, element, side, span)
                .map_err(|reason| error("E0346", &reason))?;
            let orientation = if side == ScalarSide::Left {
                crate::types::Orientation::Column
            } else {
                crate::types::Orientation::Row
            };
            self.types.intern_matrix_view(element, false);
            self.types.intern_vector_view(element, orientation, false);
            let ty = self.types.intern_vector(element, orientation);
            return Ok(Checked {
                expr: HirExpr {
                    kind: HirExprKind::AlgebraicProduct {
                        left: Box::new(l.expr),
                        right: Box::new(r.expr),
                        element_type: element,
                        product_op,
                        product,
                    },
                    ty,
                    span,
                },
                constant: None,
            });
        }
        let left_math = lv.is_some() || lm.is_some();
        let right_math = rv.is_some() || rm.is_some();
        if left_math == right_math {
            return Err(error(
                "E0342",
                "algebraic multiplication pairing unsupported; expected scaling, Row × Column, Column × Row, Matrix × Column, Row × Matrix or Matrix × Matrix",
            ));
        }
        let (element, orientation, scalar_ty, scalar_side) = if left_math {
            (
                lv.map_or_else(|| lm.unwrap(), |v| v.0),
                lv.map(|v| v.1),
                r.expr.ty,
                ScalarSide::Right,
            )
        } else {
            (
                rv.map_or_else(|| rm.unwrap(), |v| v.0),
                rv.map(|v| v.1),
                l.expr.ty,
                ScalarSide::Left,
            )
        };
        let element_op = math_element_op(self.types, element, BehavioralCapability::Mul)
            .map_err(|reason| error("E0346", &reason))?;
        if scalar_ty != element {
            return Err(error(
                "E0343",
                "scalar and element canonical types must match exactly; no promotion",
            ));
        }
        let (ty, kind) = if let Some(orientation) = orientation {
            self.types.intern_vector_view(element, orientation, false);
            (
                self.types.intern_vector(element, orientation),
                HirExprKind::VectorScalarMultiply {
                    left: Box::new(l.expr),
                    right: Box::new(r.expr),
                    scalar_side,
                    element_type: element,
                    op: element_op,
                    orientation,
                },
            )
        } else {
            self.types.intern_matrix_view(element, false);
            (
                self.types.intern_matrix(element),
                HirExprKind::MatrixScalarMultiply {
                    left: Box::new(l.expr),
                    right: Box::new(r.expr),
                    scalar_side,
                    element_type: element,
                    op: element_op,
                },
            )
        };
        Ok(Checked {
            expr: HirExpr { kind, ty, span },
            constant: None,
        })
    }
}

/// Canonical symbolic/concrete Zero value; shared by every reduction and substitution.
pub(super) fn zero_value(types: &TypeArena, ty: TypeId, span: Span) -> Option<HirExpr> {
    if !types.guarantees_capability(ty, Capability::Algebraic(AlgebraicCapability::Zero)) {
        return None;
    }
    let kind = match types.get(ty)? {
        TypeData::GenericParam(_) => HirExprKind::AlgebraicValue {
            capability: AlgebraicCapability::Zero,
        },
        TypeData::Integer(_) => HirExprKind::Int(0),
        TypeData::Float(FloatType::Float32) => HirExprKind::Float(FloatValue::Float32(0)),
        TypeData::Float(FloatType::Float64) => HirExprKind::Float(FloatValue::Float64(0)),
        _ => return None,
    };
    Some(HirExpr { kind, ty, span })
}

pub(super) fn matrix_matrix_recipe(
    types: &TypeArena,
    element: TypeId,
    span: Span,
) -> Result<(MathElementOp, AlgebraicProductKind), String> {
    if !types.guarantees_capability(element, Capability::Storable) {
        return Err("algebraic multiplication missing capability Storable".into());
    }
    let (mul, inner) = vector_product_recipe(types, element, true, span)?;
    let AlgebraicProductKind::Inner {
        accumulate_op,
        zero,
        ..
    } = inner
    else {
        unreachable!()
    };
    Ok((
        mul,
        AlgebraicProductKind::MatrixMatrix {
            shape_check: MathShapeCheck::MatrixColumnsMatrixRows,
            output_rows: (ScalarSide::Left, MatrixProductExtent::Rows),
            output_columns: (ScalarSide::Right, MatrixProductExtent::Columns),
            contraction_extent: (ScalarSide::Left, MatrixProductExtent::Columns),
            accumulate_op,
            zero,
        },
    ))
}

pub(super) fn matrix_vector_recipe(
    types: &TypeArena,
    element: TypeId,
    side: ScalarSide,
    span: Span,
) -> Result<(MathElementOp, AlgebraicProductKind), String> {
    if !types.guarantees_capability(element, Capability::Storable) {
        return Err("algebraic multiplication missing capability Storable".into());
    }
    let (mul, inner) = vector_product_recipe(types, element, true, span)?;
    let AlgebraicProductKind::Inner {
        accumulate_op,
        zero,
        ..
    } = inner
    else {
        unreachable!()
    };
    let left = side == ScalarSide::Left;
    Ok((
        mul,
        AlgebraicProductKind::MatrixVector {
            matrix_side: side,
            shape_check: if left {
                MathShapeCheck::MatrixColumnsVectorDimension
            } else {
                MathShapeCheck::VectorDimensionMatrixRows
            },
            result_extent: if left {
                MatrixProductExtent::Rows
            } else {
                MatrixProductExtent::Columns
            },
            contraction_extent: if left {
                MatrixProductExtent::Columns
            } else {
                MatrixProductExtent::Rows
            },
            accumulate_op,
            zero,
        },
    ))
}

pub(super) fn vector_product_recipe(
    types: &TypeArena,
    element: TypeId,
    inner: bool,
    span: Span,
) -> Result<(MathElementOp, AlgebraicProductKind), String> {
    let mut requirements = vec![
        Capability::Copy,
        Capability::Behavioral(BehavioralCapability::Mul),
    ];
    if inner {
        requirements.extend([
            Capability::Behavioral(BehavioralCapability::Add),
            Capability::Algebraic(AlgebraicCapability::Zero),
        ]);
    } else {
        requirements.push(Capability::Storable);
    }
    let missing = requirements
        .into_iter()
        .filter(|c| !types.guarantees_capability(element, *c))
        .map(|c| c.to_string())
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(format!(
            "algebraic multiplication missing capabilities {}",
            missing.join(" + ")
        ));
    }
    let op = |behavior| {
        if types.generic_param(element).is_some() {
            MathElementOp::Behavioral(behavior)
        } else {
            MathElementOp::Concrete(
                concrete_behavior_op(types, element, behavior).expect("proved built-in behavior"),
            )
        }
    };
    Ok((
        op(BehavioralCapability::Mul),
        if inner {
            AlgebraicProductKind::Inner {
                shape_check: MathShapeCheck::VectorDimension,
                accumulate_op: op(BehavioralCapability::Add),
                zero: Box::new(zero_value(types, element, span).expect("proved Zero")),
            }
        } else {
            AlgebraicProductKind::Outer {
                rows: ScalarSide::Left,
                columns: ScalarSide::Right,
            }
        },
    ))
}

pub(super) fn math_element_op(
    types: &TypeArena,
    element: TypeId,
    behavior: BehavioralCapability,
) -> Result<MathElementOp, String> {
    if matches!(types.get(element), Some(TypeData::GenericParam(_))) {
        let missing = [
            Capability::Storable,
            Capability::Copy,
            Capability::Behavioral(behavior),
        ]
        .into_iter()
        .filter(|cap| !types.guarantees_capability(element, *cap))
        .map(|cap| cap.to_string())
        .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Err(format!(
                "element type {} for mathematical {:?} requires Storable + Copy + {}; missing {}",
                format_type(types, element, &[], &[]),
                behavior,
                behavior,
                missing.join(" + "),
            ));
        }
        Ok(MathElementOp::Behavioral(behavior))
    } else {
        concrete_behavior_op(types, element, behavior)
            .map(MathElementOp::Concrete)
            .ok_or_else(|| {
                format!(
                    "element must be a concrete built-in arithmetic scalar supporting {behavior}"
                )
            })
    }
}

pub(super) fn verify_math_element_op(
    types: &TypeArena,
    element: TypeId,
    op: MathElementOp,
    behavior: BehavioralCapability,
    sigs: VerificationSignatures<'_>,
) -> Result<(), String> {
    if matches!(op, MathElementOp::Behavioral(_))
        && matches!(sigs, VerificationSignatures::Concrete(_))
    {
        return Err("unresolved behavioral mathematical kernel reached concrete HIR".into());
    }
    let expected = math_element_op(types, element, behavior)?;
    if op != expected {
        return Err("HIR mathematical element operation/source operator metadata invalid".into());
    }
    Ok(())
}

/// Reification of a behavioral contract into the existing concrete scalar IR.
pub(super) fn concrete_behavior_op(
    types: &TypeArena,
    ty: TypeId,
    behavior: BehavioralCapability,
) -> Option<HirBinaryOp> {
    if !types.satisfies_behavior(ty, behavior) {
        return None;
    }
    Some(match (behavior, types.float_info(ty).is_some()) {
        (BehavioralCapability::Add, false) => HirBinaryOp::AddIntegerChecked,
        (BehavioralCapability::Sub, false) => HirBinaryOp::SubtractIntegerChecked,
        (BehavioralCapability::Mul, false) => HirBinaryOp::MultiplyIntegerChecked,
        (BehavioralCapability::Add, true) => HirBinaryOp::AddFloat,
        (BehavioralCapability::Sub, true) => HirBinaryOp::SubtractFloat,
        (BehavioralCapability::Mul, true) => HirBinaryOp::MultiplyFloat,
    })
}
