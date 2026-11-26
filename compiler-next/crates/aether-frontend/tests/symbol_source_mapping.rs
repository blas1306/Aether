//! Source-facing declaration fact regressions.

use aether_frontend::{CompilerEntityId, DeclarationKind, SourceFile, analyze, parse_source};

#[test]
fn structural_declarations_keep_exact_name_spans_and_official_identity() {
    let source = "// é e\u{301} 😀\r\nstruct Box<T>{int value;}\r\nenum Choice{One,Two}\r\nint helper<T>(T value){return 1;}\r\nint main(){return helper<int>(1);}";
    let hir = analyze(parse_source(&SourceFile::new("unicode.ae", source)).unwrap()).unwrap();
    let facts = hir.semantic_facts().declarations();

    assert_eq!(facts.len(), 7);
    assert_eq!(
        facts
            .iter()
            .map(|fact| fact.name.as_str())
            .collect::<Vec<_>>(),
        ["Box", "value", "Choice", "One", "Two", "helper", "main"]
    );
    for fact in facts {
        assert_eq!(&source[fact.name_span.start..fact.name_span.end], fact.name);
        assert_eq!(fact.full_span.source, fact.name_span.source);
        assert!(fact.full_span.start <= fact.name_span.start);
        assert!(fact.name_span.end <= fact.full_span.end);
    }

    assert!(matches!(facts[0].entity, CompilerEntityId::Struct(_)));
    assert_eq!(facts[0].kind, DeclarationKind::Struct);
    assert_eq!(facts[1].owner, Some(facts[0].entity));
    assert!(matches!(facts[1].entity, CompilerEntityId::Field(_)));
    assert!(matches!(facts[2].entity, CompilerEntityId::Enum(_)));
    assert_eq!(facts[2].kind, DeclarationKind::Enum);
    assert_eq!(facts[3].owner, Some(facts[2].entity));
    assert_eq!(facts[4].owner, Some(facts[2].entity));
    assert!(matches!(facts[5].entity, CompilerEntityId::Function(_)));
    assert_eq!(facts[5].kind, DeclarationKind::Function);
    assert!(facts[5].logical.is_some());
}

#[test]
fn facts_are_deterministic_and_exclude_synthetic_lambdas() {
    let source = "int helper(){return 1;} int main(){var f=()=>1;return helper();}";
    let first = analyze(parse_source(&SourceFile::new("main.ae", source)).unwrap()).unwrap();
    let second = analyze(parse_source(&SourceFile::new("main.ae", source)).unwrap()).unwrap();

    assert_eq!(first.semantic_facts(), second.semantic_facts());
    assert_eq!(
        first
            .semantic_facts()
            .declarations()
            .iter()
            .map(|fact| fact.name.as_str())
            .collect::<Vec<_>>(),
        ["helper", "main"]
    );
}
