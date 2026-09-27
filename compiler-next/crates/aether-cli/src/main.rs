//! Official entry point for the Rust Aether CLI.

use std::env;
use std::process;

fn main() {
    process::exit(aether_cli::run(env::args_os().skip(1)));
}
