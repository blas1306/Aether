//! Flat nominal class-backed interface contracts and verified witness recipes.
#![allow(missing_docs)]
use crate::{
    AstParameter, AstType, ClassId, FunctionId, ModuleId, Span, TypeArena, TypeData, TypeId,
};

#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct InterfaceId(pub u32);
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct RequirementId {
    pub interface: InterfaceId,
    pub index: u32,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct WitnessId(pub u32);
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstInterface {
    pub name: String,
    pub public: bool,
    pub requirements: Vec<AstRequirement>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct AstRequirement {
    pub name: String,
    pub mutable: bool,
    pub parameters: Vec<AstParameter>,
    pub result: AstType,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct RequirementInfo {
    pub id: RequirementId,
    pub name: String,
    pub mutable: bool,
    pub parameters: Vec<TypeId>,
    pub result: TypeId,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct InterfaceInfo {
    pub id: InterfaceId,
    pub module: ModuleId,
    pub name: String,
    pub public: bool,
    pub requirements: Vec<RequirementInfo>,
    pub span: Span,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WitnessSlot {
    pub requirement: RequirementId,
    pub method: FunctionId,
}
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct WitnessInfo {
    pub id: WitnessId,
    pub class: ClassId,
    pub interface: InterfaceId,
    pub slots: Vec<WitnessSlot>,
}

impl TypeArena {
    #[must_use]
    pub fn interfaces(&self) -> &[InterfaceInfo] {
        &self.interfaces
    }
    #[must_use]
    pub fn witnesses(&self) -> &[WitnessInfo] {
        &self.witnesses
    }
    pub fn register_interface_definition(&mut self, i: InterfaceInfo) {
        if i.id.0 as usize == self.interfaces.len() {
            self.interfaces.push(i);
        } else {
            let index = i.id.0 as usize;
            self.interfaces[index] = i;
        }
    }
    pub fn register_witness(&mut self, w: WitnessInfo) {
        if w.id.0 as usize == self.witnesses.len() {
            self.witnesses.push(w);
        } else {
            let index = w.id.0 as usize;
            self.witnesses[index] = w;
        }
    }
    #[must_use]
    pub fn interface_id(&self, ty: TypeId) -> Option<InterfaceId> {
        match self.get(ty)? {
            TypeData::Interface(id) => Some(*id),
            _ => None,
        }
    }
    #[must_use]
    pub fn interface_identity(&self, ty: TypeId) -> Option<InterfaceId> {
        match self.get(ty)? {
            TypeData::Interface(id) | TypeData::InterfaceKeepalive { interface: id, .. } => {
                Some(*id)
            }
            _ => None,
        }
    }
    #[must_use]
    pub fn is_object_owner(&self, ty: TypeId) -> bool {
        self.class_id(ty).is_some() || self.interface_id(ty).is_some()
    }
    #[must_use]
    pub fn requirement(&self, id: RequirementId) -> Option<&RequirementInfo> {
        self.interfaces
            .get(id.interface.0 as usize)?
            .requirements
            .get(id.index as usize)
            .filter(|r| r.id == id)
    }
}

/// Reconstruct every conformance from nominal relations and exact method contracts.
/// Phase-local signature verification separately binds method contracts to bodies.
#[allow(clippy::too_many_lines)]
pub fn verify_interface_metadata(types: &TypeArena) -> Result<(), String> {
    use std::collections::BTreeSet;
    for (_, data) in types.entries() {
        if let TypeData::Interface(id) | TypeData::InterfaceKeepalive { interface: id, .. } = data
            && types.interfaces().get(id.0 as usize).is_none()
        {
            return Err("unknown interface type identity".into());
        }
    }
    for (index, i) in types.interfaces().iter().enumerate() {
        if i.id.0 as usize != index || types.id_of(TypeData::Interface(i.id)).is_none() {
            return Err("invalid InterfaceId".into());
        }
        let mut names = BTreeSet::new();
        for (slot, r) in i.requirements.iter().enumerate() {
            if r.id
                != (RequirementId {
                    interface: i.id,
                    index: u32::try_from(slot).map_err(|_| "too many interface requirements")?,
                })
                || !names.insert(&r.name)
            {
                return Err("invalid or duplicate RequirementId".into());
            }
            for ty in r.parameters.iter().chain(std::iter::once(&r.result)) {
                if types.get(*ty).is_none()
                    || types.contains_generic(*ty)
                    || matches!(
                        types.get(*ty),
                        Some(TypeData::ClassToken { .. } | TypeData::InterfaceKeepalive { .. })
                    )
                {
                    return Err("invalid interface signature type".into());
                }
                if i.public
                    && (types.class_id(*ty).is_some_and(|c| {
                        types.classes().get(c.0 as usize).is_none_or(|c| !c.public)
                    }) || types.interface_id(*ty).is_some_and(|i| {
                        types
                            .interfaces()
                            .get(i.0 as usize)
                            .is_none_or(|i| !i.public)
                    }))
                {
                    return Err("public interface exposes internal type".into());
                }
            }
            if types.contains_reference(r.result) || types.contains_view(r.result) {
                return Err("interface cannot return borrowed storage".into());
            }
        }
    }
    let mut pairs = BTreeSet::new();
    for c in types.classes() {
        let mut seen = BTreeSet::new();
        for i in &c.interfaces {
            let info = types
                .interfaces()
                .get(i.0 as usize)
                .ok_or("unknown conformance InterfaceId")?;
            if !seen.insert(i) {
                return Err("duplicate canonical interface conformance".into());
            }
            if c.public && !info.public {
                return Err("public class conformance exposes internal interface".into());
            }
            if types
                .witnesses()
                .iter()
                .filter(|w| w.class == c.id && w.interface == *i)
                .count()
                != 1
            {
                return Err("conformance must have exactly one witness".into());
            }
        }
    }
    for (index, w) in types.witnesses().iter().enumerate() {
        let c = types
            .classes()
            .get(w.class.0 as usize)
            .ok_or("invalid witness ClassId")?;
        let i = types
            .interfaces()
            .get(w.interface.0 as usize)
            .ok_or("invalid witness InterfaceId")?;
        if w.id.0 as usize != index
            || !pairs.insert((w.class, w.interface))
            || !c.interfaces.contains(&w.interface)
            || w.slots.len() != i.requirements.len()
        {
            return Err("invalid nominal witness association or coverage".into());
        }
        for (slot, r) in w.slots.iter().zip(&i.requirements) {
            let (owner, m) = types
                .class_method(slot.method)
                .ok_or("invalid witness MethodId")?;
            if slot.requirement != r.id
                || owner != c.id
                || m.initializing
                || !m.public
                || m.name != r.name
                || m.mutable != r.mutable
                || m.parameters != r.parameters
                || m.result != r.result
            {
                return Err("interface requirement needs an exact public method contract".into());
            }
        }
    }
    Ok(())
}
