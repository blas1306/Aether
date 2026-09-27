//! Administrative and serving entry point for the V1 reference registry.

use std::fmt::Write as _;
use std::fs::File;
use std::io::Read as _;
use std::net::TcpListener;
use std::path::PathBuf;

use aether_registry::{RegistryStore, serve};

fn main() {
    if let Err(message) = run() {
        eprintln!("aether-registry: error: {message}");
        std::process::exit(2);
    }
}

fn run() -> Result<(), String> {
    let arguments = std::env::args().skip(1).collect::<Vec<_>>();
    match arguments.as_slice() {
        [command, root, bind] if command == "serve" => {
            let listener = TcpListener::bind(bind)
                .map_err(|error| format!("cannot bind registry listener: {error}"))?;
            let store = RegistryStore::open(PathBuf::from(root))?;
            serve(&listener, &store)
        }
        [command, root, account] if command == "create-token" => {
            let mut random = [0_u8; 32];
            File::open("/dev/urandom")
                .and_then(|mut file| file.read_exact(&mut random))
                .map_err(|error| format!("cannot generate registry credential: {error}"))?;
            let token = random.iter().fold(String::new(), |mut output, byte| {
                write!(output, "{byte:02x}").expect("writing to a string cannot fail");
                output
            });
            RegistryStore::open(PathBuf::from(root))?.provision_token(account, &token)?;
            println!("{token}");
            Ok(())
        }
        [command, root, package, version, value] if command == "set-official" => {
            let official = value
                .parse::<bool>()
                .map_err(|_| "official value must be true or false".to_owned())?;
            RegistryStore::open(PathBuf::from(root))?
                .set_official(package, version, official)
        }
        _ => Err("usage: aether-registry serve <storage> <bind>\n       aether-registry create-token <storage> <account>\n       aether-registry set-official <storage> <package> <version> <true|false>".to_owned()),
    }
}
