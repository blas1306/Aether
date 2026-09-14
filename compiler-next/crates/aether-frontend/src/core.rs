//! Closed, versioned Core/prelude symbol identities and call contracts.
#![allow(missing_docs)]

use crate::{TypeArena, TypeId};

pub const CORE_V1_PROFILE: u16 = 1;

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(u16)]
pub enum CoreSymbol {
    Print = 0,
    Println = 1,
    ByteLength = 2,
    Abs = 3,
    Min = 4,
    Max = 5,
    Clamp = 6,
    Sqrt = 7,
    Exp = 8,
    Ln = 9,
    Sin = 10,
    Cos = 11,
    Tan = 12,
}

impl CoreSymbol {
    #[must_use]
    pub const fn member(self) -> &'static str {
        match self {
            Self::Print => "print",
            Self::Println => "println",
            Self::ByteLength => "byteLength",
            Self::Abs => "abs",
            Self::Min => "min",
            Self::Max => "max",
            Self::Clamp => "clamp",
            Self::Sqrt => "sqrt",
            Self::Exp => "exp",
            Self::Ln => "ln",
            Self::Sin => "sin",
            Self::Cos => "cos",
            Self::Tan => "tan",
        }
    }

    #[must_use]
    pub const fn ordinal(self) -> u16 {
        self as u16
    }
}

pub const PRELUDE_V1: &[(&str, CoreSymbol)] = &[
    ("print", CoreSymbol::Print),
    ("println", CoreSymbol::Println),
    ("byteLength", CoreSymbol::ByteLength),
    ("abs", CoreSymbol::Abs),
    ("min", CoreSymbol::Min),
    ("max", CoreSymbol::Max),
    ("clamp", CoreSymbol::Clamp),
    ("sqrt", CoreSymbol::Sqrt),
    ("exp", CoreSymbol::Exp),
    ("ln", CoreSymbol::Ln),
    ("sin", CoreSymbol::Sin),
    ("cos", CoreSymbol::Cos),
    ("tan", CoreSymbol::Tan),
];

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct CoreSymbolKey {
    pub profile: u16,
    pub ordinal: u16,
    pub member: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CoreFunction {
    pub symbol: CoreSymbol,
    pub identity: CoreSymbolKey,
    pub parameter_type: TypeId,
}

impl CoreFunction {
    #[must_use]
    pub fn resolve(symbol: CoreSymbol, parameter_type: TypeId) -> Self {
        Self {
            symbol,
            identity: CoreSymbolKey {
                profile: CORE_V1_PROFILE,
                ordinal: symbol.ordinal(),
                member: symbol.member().into(),
            },
            parameter_type,
        }
    }

    #[must_use]
    pub const fn arity(&self) -> usize {
        match self.symbol {
            CoreSymbol::Min | CoreSymbol::Max => 2,
            CoreSymbol::Clamp => 3,
            _ => 1,
        }
    }

    #[must_use]
    pub const fn result_type(&self) -> TypeId {
        match self.symbol {
            CoreSymbol::Print | CoreSymbol::Println => TypeId::BOOL,
            CoreSymbol::ByteLength => TypeId::USIZE,
            _ => self.parameter_type,
        }
    }
}

#[must_use]
pub fn prelude_symbol(spelling: &str) -> Option<CoreSymbol> {
    PRELUDE_V1
        .iter()
        .find_map(|(name, symbol)| (*name == spelling).then_some(*symbol))
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CoreCall<O> {
    pub function: CoreFunction,
    pub arguments: Vec<O>,
}

impl<O> CoreCall<O> {
    #[must_use]
    pub fn operands(&self) -> Vec<&O> {
        self.arguments.iter().collect()
    }

    pub fn map<P, E>(self, mut f: impl FnMut(O) -> Result<P, E>) -> Result<CoreCall<P>, E> {
        Ok(CoreCall {
            function: self.function,
            arguments: self
                .arguments
                .into_iter()
                .map(&mut f)
                .collect::<Result<Vec<_>, _>>()?,
        })
    }
}

pub fn verify_core_call<O>(
    call: &CoreCall<O>,
    result: TypeId,
    types: &TypeArena,
    operand_ty: impl Fn(&O) -> Result<TypeId, String>,
) -> Result<(), String> {
    let function = &call.function;
    let canonical = CoreFunction::resolve(function.symbol, function.parameter_type);
    if *function != canonical {
        return Err("Core function identity is not canonical for Core profile v1".into());
    }
    if call.arguments.len() != function.arity() || result != function.result_type() {
        return Err("Core function arity or result type is invalid".into());
    }
    for argument in &call.arguments {
        if operand_ty(argument)? != function.parameter_type {
            return Err("Core function operand type disagrees with its resolved signature".into());
        }
    }
    let valid = match function.symbol {
        CoreSymbol::Print | CoreSymbol::Println | CoreSymbol::ByteLength => {
            function.parameter_type == TypeId::STRING
        }
        CoreSymbol::Abs => {
            types
                .integer_info(function.parameter_type)
                .is_some_and(crate::IntegerType::is_signed)
                || types.float_info(function.parameter_type).is_some()
        }
        CoreSymbol::Min | CoreSymbol::Max | CoreSymbol::Clamp => {
            types.is_numeric(function.parameter_type)
        }
        CoreSymbol::Sqrt
        | CoreSymbol::Exp
        | CoreSymbol::Ln
        | CoreSymbol::Sin
        | CoreSymbol::Cos
        | CoreSymbol::Tan => types.float_info(function.parameter_type).is_some(),
    };
    valid
        .then_some(())
        .ok_or_else(|| "Core function resolved to an unsupported signature".into())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::BTreeSet;

    #[test]
    fn v1_manifest_is_closed_unique_and_canonical() {
        assert_eq!(PRELUDE_V1.len(), 13);
        assert_eq!(
            PRELUDE_V1
                .iter()
                .map(|(name, _)| *name)
                .collect::<BTreeSet<_>>()
                .len(),
            PRELUDE_V1.len()
        );
        assert_eq!(
            PRELUDE_V1
                .iter()
                .map(|(_, symbol)| symbol.ordinal())
                .collect::<BTreeSet<_>>()
                .len(),
            PRELUDE_V1.len()
        );
        for (name, symbol) in PRELUDE_V1 {
            assert_eq!(*name, symbol.member());
            assert_eq!(prelude_symbol(name), Some(*symbol));
        }
        assert_eq!(prelude_symbol("List"), None);
        assert_eq!(prelude_symbol("std"), None);
    }
}
