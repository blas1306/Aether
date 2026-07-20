//! Type hierarchy used by Aether IR values.

use std::fmt;

/// The complete Aether IR type hierarchy.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub enum IRType {
    /// A signed 32-bit Aether integer.
    Int(IntType),
    /// A single-precision floating-point value.
    Float(FloatType),
    /// A double-precision floating-point value.
    Double(DoubleType),
    /// A boolean value.
    Bool(BoolType),
    /// A UTF-8 string value.
    String(StringType),
    /// The absence of a value.
    Void(VoidType),
    /// A typed function reference.
    Function(FunctionType),
    /// A double-precision complex value.
    Complex(ComplexType),
    /// A nullable value.
    Nullable(NullableType),
    /// A dynamically sized list.
    List(ListType),
    /// A dynamically sized array.
    Array(ArrayType),
    /// An oriented vector.
    Vector(VectorType),
    /// A matrix.
    Matrix(MatrixType),
    /// A nominal struct value.
    Struct(StructType),
    /// The internal pair returned by a struct method.
    MethodResult(MethodResultType),
    /// A nominal class reference.
    ClassRef(ClassRefType),
    /// A nominal interface value.
    Interface(InterfaceType),
    /// A nominal enum value.
    Enum(EnumType),
}

/// The `int` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct IntType;

/// The `float` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct FloatType;

/// The `double` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct DoubleType;

/// The `bool` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct BoolType;

/// The `string` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct StringType;

/// The `void` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct VoidType;

/// The `complex` IR type.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
pub struct ComplexType;

/// A function signature retained by an IR function reference.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct FunctionType {
    /// Parameter types in declaration order.
    pub parameter_types: Vec<IRType>,
    /// Function return type.
    pub return_type: Box<IRType>,
}

/// A nullable value type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct NullableType {
    /// Type carried by non-null values.
    pub inner: Box<IRType>,
}

/// A dynamically sized list type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct ListType {
    /// List element type.
    pub element: Box<IRType>,
}

/// A dynamically sized array type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct ArrayType {
    /// Array element type.
    pub element: Box<IRType>,
}

/// A vector type with optional row or column orientation.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct VectorType {
    /// Vector element type.
    pub element: Box<IRType>,
    /// Orientation retained as the spelling used by the Python IR.
    pub orientation: Option<String>,
}

/// A matrix type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct MatrixType {
    /// Matrix element type.
    pub element: Box<IRType>,
}

/// A nominal struct type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct StructType {
    /// Struct name.
    pub name: String,
}

/// Internal ABI value returned by a struct method.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct MethodResultType {
    /// Struct receiver returned by the method.
    pub receiver: StructType,
    /// Source-level result value type.
    pub value: Box<IRType>,
}

/// A nominal class reference type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct ClassRefType {
    /// Class name.
    pub name: String,
}

/// A nominal interface type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct InterfaceType {
    /// Interface name.
    pub name: String,
}

/// A nominal enum type.
#[derive(Clone, Debug, PartialEq, Eq, Hash)]
pub struct EnumType {
    /// Canonical enum name.
    pub name: String,
    /// Variant names in declaration order.
    pub variants: Vec<String>,
    /// Optional source-facing enum name.
    pub display_name: Option<String>,
}

macro_rules! impl_ir_type_conversion {
    ($type:ty, $variant:ident) => {
        impl From<$type> for IRType {
            fn from(value: $type) -> Self {
                Self::$variant(value)
            }
        }
    };
}

impl_ir_type_conversion!(IntType, Int);
impl_ir_type_conversion!(FloatType, Float);
impl_ir_type_conversion!(DoubleType, Double);
impl_ir_type_conversion!(BoolType, Bool);
impl_ir_type_conversion!(StringType, String);
impl_ir_type_conversion!(VoidType, Void);
impl_ir_type_conversion!(FunctionType, Function);
impl_ir_type_conversion!(ComplexType, Complex);
impl_ir_type_conversion!(NullableType, Nullable);
impl_ir_type_conversion!(ListType, List);
impl_ir_type_conversion!(ArrayType, Array);
impl_ir_type_conversion!(VectorType, Vector);
impl_ir_type_conversion!(MatrixType, Matrix);
impl_ir_type_conversion!(StructType, Struct);
impl_ir_type_conversion!(MethodResultType, MethodResult);
impl_ir_type_conversion!(ClassRefType, ClassRef);
impl_ir_type_conversion!(InterfaceType, Interface);
impl_ir_type_conversion!(EnumType, Enum);

impl fmt::Display for IRType {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Int(_) => formatter.write_str("int"),
            Self::Float(_) => formatter.write_str("float"),
            Self::Double(_) => formatter.write_str("double"),
            Self::Bool(_) => formatter.write_str("bool"),
            Self::String(_) => formatter.write_str("string"),
            Self::Void(_) => formatter.write_str("void"),
            Self::Complex(_) => formatter.write_str("complex"),
            Self::Function(function) => {
                write!(formatter, "{}(", function.return_type)?;
                for (index, parameter) in function.parameter_types.iter().enumerate() {
                    if index > 0 {
                        formatter.write_str(", ")?;
                    }
                    write!(formatter, "{parameter}")?;
                }
                formatter.write_str(")")
            }
            Self::Nullable(nullable) => write!(formatter, "nullable<{}>", nullable.inner),
            Self::List(list) => write!(formatter, "list<{}>", list.element),
            Self::Array(array) => write!(formatter, "array<{}>", array.element),
            Self::Vector(vector) => match &vector.orientation {
                Some(orientation) => {
                    write!(formatter, "vector<{}, {orientation}>", vector.element)
                }
                None => write!(formatter, "vector<{}>", vector.element),
            },
            Self::Matrix(matrix) => write!(formatter, "matrix<{}>", matrix.element),
            Self::Struct(struct_type) => write!(formatter, "struct {}", struct_type.name),
            Self::MethodResult(result) => write!(
                formatter,
                "method_result<{}, {}>",
                result.receiver.name, result.value
            ),
            Self::ClassRef(class) => write!(formatter, "class {}", class.name),
            Self::Interface(interface) => write!(formatter, "interface {}", interface.name),
            Self::Enum(enum_type) => write!(formatter, "enum {}", enum_type.name),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn formats_nested_types_like_the_python_ir() {
        let type_ = FunctionType {
            parameter_types: vec![IntType.into(), BoolType.into()],
            return_type: Box::new(
                ListType {
                    element: Box::new(StringType.into()),
                }
                .into(),
            ),
        };

        assert_eq!(IRType::from(type_).to_string(), "list<string>(int, bool)");
    }

    #[test]
    fn formats_oriented_vectors() {
        let type_ = VectorType {
            element: Box::new(DoubleType.into()),
            orientation: Some("row".to_owned()),
        };

        assert_eq!(IRType::from(type_).to_string(), "vector<double, row>");
    }
}
