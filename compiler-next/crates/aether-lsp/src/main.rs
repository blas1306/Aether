//! Executable entry point for the native diagnostics server.

fn main() {
    let stdio = std::env::args()
        .skip(1)
        .any(|argument| argument == "--stdio");
    if !stdio {
        eprintln!("usage: aether-lsp --stdio");
        std::process::exit(2);
    }
    std::process::exit(aether_lsp::serve_stdio());
}
