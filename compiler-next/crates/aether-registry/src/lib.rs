//! Minimal persistent reference service for the Aether Package Registry V1 protocol.

use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::{Path, PathBuf};

use aether_package::{
    PackageName, PublishOutcome, RegistryProtocolMetadata, RegistryVersion, inspect_publication,
};
use fs2::FileExt as _;
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

const MAX_ARCHIVE: u64 = 64 * 1024 * 1024;

/// Persistent filesystem-backed registry state.
#[derive(Clone, Debug)]
pub struct RegistryStore {
    root: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct TokenRecord {
    account: String,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Owners {
    owners: BTreeSet<String>,
}

/// Result of one authenticated publication.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StoredPublication {
    /// Whether this created a version or was an identical retry.
    pub outcome: PublishOutcome,
    /// Server-derived immutable metadata.
    pub metadata: RegistryProtocolMetadata,
}

impl RegistryStore {
    /// Open or create a durable registry root.
    pub fn open(root: impl Into<PathBuf>) -> Result<Self, String> {
        let store = Self { root: root.into() };
        for directory in ["packages", "tokens", "tmp"] {
            fs::create_dir_all(store.root.join(directory))
                .map_err(|error| format!("cannot initialize registry storage: {error}"))?;
        }
        OpenOptions::new()
            .create(true)
            .append(true)
            .open(store.root.join("registry.lock"))
            .map_err(|error| format!("cannot initialize registry lock: {error}"))?;
        Ok(store)
    }

    /// Provision an administrative bearer token without retaining its plaintext.
    pub fn provision_token(&self, account: &str, token: &str) -> Result<(), String> {
        validate_account(account)?;
        if token.len() < 24 {
            return Err("registry tokens must contain at least 24 characters".to_owned());
        }
        let digest = token_digest(token);
        write_new_json(
            &self.root.join("tokens").join(format!("{digest}.json")),
            &TokenRecord {
                account: account.to_owned(),
            },
        )
    }

    /// Publish immutable bytes after independently validating auth and archive metadata.
    pub fn publish(
        &self,
        requested_name: &str,
        requested_version: &str,
        token: &str,
        declared_checksum: &str,
        archive: &[u8],
    ) -> Result<StoredPublication, String> {
        PackageName::new(requested_name.to_owned())?;
        Version::parse(requested_version)
            .map_err(|error| format!("invalid requested package version: {error}"))?;
        let account = self.authenticate(token)?;
        if archive.len() as u64 > MAX_ARCHIVE {
            return Err("publication archive exceeds registry limit".to_owned());
        }
        let checksum = format!("sha256:{:x}", Sha256::digest(archive));
        if checksum != declared_checksum {
            return Err("publication checksum does not match exact request bytes".to_owned());
        }
        let contents = inspect_publication(archive, MAX_ARCHIVE)?;
        if contents.name != requested_name || contents.version != requested_version {
            return Err("request identity does not match the archived manifest".to_owned());
        }
        let metadata = RegistryProtocolMetadata {
            name: contents.name,
            version: contents.version,
            yanked: false,
            official: false,
            checksum,
            dependencies: contents.dependencies,
            archive_size: archive.len() as u64,
        };

        let lock = self.lock()?;
        let package = self.package_root(requested_name);
        let owners_path = package.join("owners.json");
        let first = !package.exists();
        if !first {
            let owners: Owners = read_json(&owners_path, "package owners")?;
            if !owners.owners.contains(&account) {
                drop(lock);
                return Err("authenticated account does not own this package".to_owned());
            }
        }
        let version_root = package.join("versions").join(requested_version);
        if version_root.exists() {
            let existing: RegistryProtocolMetadata =
                read_json(&version_root.join("metadata.json"), "version metadata")?;
            let existing_archive = fs::read(version_root.join("archive.tar"))
                .map_err(|error| format!("cannot read existing immutable archive: {error}"))?;
            drop(lock);
            if same_immutable_metadata(&existing, &metadata) && existing_archive == archive {
                return Ok(StoredPublication {
                    outcome: PublishOutcome::Identical,
                    metadata: existing,
                });
            }
            return Err(
                "package version already exists with different immutable content".to_owned(),
            );
        }

        let serial = unique_serial();
        let stage = self
            .root
            .join("tmp")
            .join(format!("publish-{}-{serial}", std::process::id()));
        let staged_version = if first {
            stage.join("package/versions").join(requested_version)
        } else {
            stage.join("version")
        };
        let result: Result<(), String> = (|| {
            fs::create_dir_all(&staged_version)
                .map_err(|error| format!("cannot create publication staging: {error}"))?;
            write_synced(&staged_version.join("archive.tar"), archive)?;
            write_json_synced(&staged_version.join("metadata.json"), &metadata)?;
            if first {
                write_json_synced(
                    &stage.join("package/owners.json"),
                    &Owners {
                        owners: BTreeSet::from([account.clone()]),
                    },
                )?;
                fs::rename(stage.join("package"), &package)
                    .map_err(|error| format!("cannot atomically reserve package name: {error}"))?;
                sync_directory(package.parent().expect("package parent"))?;
            } else {
                fs::rename(&staged_version, &version_root).map_err(|error| {
                    format!("cannot atomically publish package version: {error}")
                })?;
                sync_directory(version_root.parent().expect("versions parent"))?;
            }
            Ok(())
        })();
        let _ = fs::remove_dir_all(&stage);
        drop(lock);
        result?;
        Ok(StoredPublication {
            outcome: PublishOutcome::Created,
            metadata,
        })
    }

    /// List exact versions, including their yank state.
    pub fn versions(&self, name: &str) -> Result<Vec<RegistryVersion>, String> {
        PackageName::new(name.to_owned())?;
        let root = self.package_root(name).join("versions");
        if !root.is_dir() {
            return Ok(Vec::new());
        }
        let mut versions = Vec::new();
        for entry in fs::read_dir(root).map_err(|error| format!("cannot list versions: {error}"))? {
            let entry = entry.map_err(|error| format!("cannot list versions: {error}"))?;
            if !entry.path().is_dir() {
                continue;
            }
            let metadata: RegistryProtocolMetadata =
                read_json(&entry.path().join("metadata.json"), "version metadata")?;
            versions.push(RegistryVersion {
                version: metadata.version,
                yanked: metadata.yanked,
            });
        }
        versions.sort_by(|left, right| left.version.cmp(&right.version));
        Ok(versions)
    }

    /// Read exact immutable metadata, whether or not the version is yanked.
    pub fn metadata(&self, name: &str, version: &str) -> Result<RegistryProtocolMetadata, String> {
        validate_identity(name, version)?;
        read_json(
            &self.version_root(name, version).join("metadata.json"),
            "version metadata",
        )
    }

    /// Read an exact immutable archive.
    pub fn archive(&self, name: &str, version: &str) -> Result<Vec<u8>, String> {
        validate_identity(name, version)?;
        fs::read(self.version_root(name, version).join("archive.tar"))
            .map_err(|error| format!("cannot read package archive: {error}"))
    }

    /// Change only yank state; archive bytes and resolutive metadata remain retained.
    pub fn yank(&self, name: &str, version: &str, token: &str, yanked: bool) -> Result<(), String> {
        validate_identity(name, version)?;
        let account = self.authenticate(token)?;
        let lock = self.lock()?;
        let owners: Owners = read_json(&self.package_root(name).join("owners.json"), "owners")?;
        if !owners.owners.contains(&account) {
            drop(lock);
            return Err("authenticated account does not own this package".to_owned());
        }
        let path = self.version_root(name, version).join("metadata.json");
        let mut metadata: RegistryProtocolMetadata = read_json(&path, "version metadata")?;
        metadata.yanked = yanked;
        replace_json(&path, &metadata)?;
        drop(lock);
        Ok(())
    }

    /// Set official attestation through local registry administration only.
    pub fn set_official(&self, name: &str, version: &str, official: bool) -> Result<(), String> {
        validate_identity(name, version)?;
        let lock = self.lock()?;
        let path = self.version_root(name, version).join("metadata.json");
        let mut metadata: RegistryProtocolMetadata = read_json(&path, "version metadata")?;
        metadata.official = official;
        replace_json(&path, &metadata)?;
        drop(lock);
        Ok(())
    }

    fn authenticate(&self, token: &str) -> Result<String, String> {
        if token.is_empty() {
            return Err("publication authorization is required".to_owned());
        }
        let record: TokenRecord = read_json(
            &self
                .root
                .join("tokens")
                .join(format!("{}.json", token_digest(token))),
            "registry credential",
        )
        .map_err(|_| "publication authorization is invalid".to_owned())?;
        Ok(record.account)
    }

    fn package_root(&self, name: &str) -> PathBuf {
        self.root.join("packages").join(name)
    }

    fn version_root(&self, name: &str, version: &str) -> PathBuf {
        self.package_root(name).join("versions").join(version)
    }

    fn lock(&self) -> Result<File, String> {
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(self.root.join("registry.lock"))
            .map_err(|error| format!("cannot open registry lock: {error}"))?;
        file.lock_exclusive()
            .map_err(|error| format!("cannot acquire registry lock: {error}"))?;
        Ok(file)
    }
}

/// Serve the V1 protocol over a supplied listener. TLS termination belongs in front of this
/// reference process; production clients still require an HTTPS origin.
pub fn serve(listener: &TcpListener, store: &RegistryStore) -> Result<(), String> {
    for stream in listener.incoming() {
        match stream {
            Ok(stream) => {
                let service = store.clone();
                std::thread::spawn(move || {
                    let _ = handle(stream, &service);
                });
            }
            Err(error) => return Err(format!("registry accept failed: {error}")),
        }
    }
    Ok(())
}

/// Accept and serve one connection, primarily for embedding and protocol qualification.
pub fn serve_one(listener: &TcpListener, store: &RegistryStore) -> Result<(), String> {
    let (stream, _) = listener
        .accept()
        .map_err(|error| format!("registry accept failed: {error}"))?;
    handle(stream, store)
}

#[allow(clippy::too_many_lines)]
fn handle(mut stream: TcpStream, store: &RegistryStore) -> Result<(), String> {
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(30)))
        .map_err(|error| format!("cannot configure request timeout: {error}"))?;
    let clone = stream
        .try_clone()
        .map_err(|error| format!("cannot read registry request: {error}"))?;
    let mut reader = BufReader::new(clone);
    let mut first = String::new();
    reader
        .read_line(&mut first)
        .map_err(|error| format!("cannot read request line: {error}"))?;
    let parts = first.split_whitespace().collect::<Vec<_>>();
    if parts.len() != 3 {
        return respond(&mut stream, 400, "text/plain", b"bad request");
    }
    let method = parts[0];
    let target = parts[1];
    let mut content_length = 0_u64;
    let mut authorization = None;
    let mut checksum = None;
    loop {
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|error| format!("cannot read request headers: {error}"))?;
        if line == "\r\n" || line == "\n" {
            break;
        }
        let Some((name, value)) = line.split_once(':') else {
            return respond(&mut stream, 400, "text/plain", b"bad header");
        };
        let value = value.trim();
        match name.to_ascii_lowercase().as_str() {
            "content-length" => {
                content_length = value
                    .parse()
                    .map_err(|_| "invalid content length".to_owned())?;
            }
            "authorization" => authorization = value.strip_prefix("Bearer ").map(ToOwned::to_owned),
            "x-aether-checksum" => checksum = Some(value.to_owned()),
            _ => {}
        }
    }
    if content_length > MAX_ARCHIVE {
        return respond(&mut stream, 413, "text/plain", b"request too large");
    }
    let body_length = usize::try_from(content_length)
        .map_err(|_| "request body cannot be represented on this platform".to_owned())?;
    let mut body = vec![0; body_length];
    reader
        .read_exact(&mut body)
        .map_err(|error| format!("cannot read request body: {error}"))?;
    let route = target.split('?').next().unwrap_or(target);
    let segments = route.trim_matches('/').split('/').collect::<Vec<_>>();
    let result = match (method, segments.as_slice()) {
        ("GET", ["v1", "packages", name, "versions"]) => store
            .versions(name)
            .and_then(|versions| json(&serde_json::json!({ "versions": versions }))),
        ("GET", ["v1", "packages", name, version]) => {
            store.metadata(name, version).and_then(|value| json(&value))
        }
        ("GET", ["v1", "packages", name, version, "archive"]) => {
            let supplied = query_parameter(target, "checksum").unwrap_or_default();
            store.metadata(name, version).and_then(|metadata| {
                if supplied != metadata.checksum {
                    return Err("archive checksum selector does not match metadata".to_owned());
                }
                store
                    .archive(name, version)
                    .map(|bytes| (200, "application/x-tar", bytes))
            })
        }
        ("POST", ["v1", "packages", name, version]) => store
            .publish(
                name,
                version,
                authorization.as_deref().unwrap_or(""),
                checksum.as_deref().unwrap_or(""),
                &body,
            )
            .and_then(|stored| json(&serde_json::json!({ "outcome": stored.outcome }))),
        ("POST", ["v1", "packages", name, version, "yank"]) => store
            .yank(name, version, authorization.as_deref().unwrap_or(""), true)
            .and_then(|()| json(&serde_json::json!({ "yanked": true }))),
        _ => return respond(&mut stream, 404, "text/plain", b"not found"),
    };
    match result {
        Ok((status, content_type, bytes)) => respond(&mut stream, status, content_type, &bytes),
        Err(message) => {
            let status = if message.contains("authorization") || message.contains("own") {
                403
            } else if message.contains("already exists") {
                409
            } else {
                400
            };
            respond(
                &mut stream,
                status,
                "text/plain",
                b"registry request rejected",
            )
        }
    }
}

fn json(value: &impl Serialize) -> Result<(u16, &'static str, Vec<u8>), String> {
    serde_json::to_vec(value)
        .map(|bytes| (200, "application/json", bytes))
        .map_err(|error| format!("cannot encode registry response: {error}"))
}

fn respond(
    stream: &mut TcpStream,
    status: u16,
    content_type: &str,
    body: &[u8],
) -> Result<(), String> {
    let reason = match status {
        200 => "OK",
        400 => "Bad Request",
        403 => "Forbidden",
        404 => "Not Found",
        409 => "Conflict",
        413 => "Content Too Large",
        _ => "Error",
    };
    write!(
        stream,
        "HTTP/1.1 {status} {reason}\r\nContent-Type: {content_type}\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
        body.len()
    )
    .and_then(|()| stream.write_all(body))
    .map_err(|error| format!("cannot write registry response: {error}"))
}

fn validate_identity(name: &str, version: &str) -> Result<(), String> {
    PackageName::new(name.to_owned())?;
    Version::parse(version)
        .map(|_| ())
        .map_err(|error| format!("invalid package version: {error}"))
}

fn validate_account(account: &str) -> Result<(), String> {
    if account.is_empty()
        || !account
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'_' | b'-'))
    {
        return Err("account must contain only ASCII letters, digits, `_`, or `-`".to_owned());
    }
    Ok(())
}

fn token_digest(token: &str) -> String {
    format!("{:x}", Sha256::digest(token.as_bytes()))
}

fn same_immutable_metadata(
    left: &RegistryProtocolMetadata,
    right: &RegistryProtocolMetadata,
) -> bool {
    left.name == right.name
        && left.version == right.version
        && left.checksum == right.checksum
        && left.dependencies == right.dependencies
        && left.archive_size == right.archive_size
}

fn query_parameter(target: &str, wanted: &str) -> Option<String> {
    let query = target.split_once('?')?.1;
    query.split('&').find_map(|part| {
        let (name, value) = part.split_once('=')?;
        (name == wanted).then(|| percent_decode(value))
    })
}

fn percent_decode(value: &str) -> String {
    let bytes = value.as_bytes();
    let mut decoded = Vec::with_capacity(bytes.len());
    let mut cursor = 0;
    while cursor < bytes.len() {
        if bytes[cursor] == b'%' && cursor + 2 < bytes.len() {
            let hex = &value[cursor + 1..cursor + 3];
            if let Ok(byte) = u8::from_str_radix(hex, 16) {
                decoded.push(byte);
                cursor += 3;
                continue;
            }
        }
        decoded.push(bytes[cursor]);
        cursor += 1;
    }
    String::from_utf8_lossy(&decoded).into_owned()
}

fn read_json<T: for<'de> Deserialize<'de>>(path: &Path, label: &str) -> Result<T, String> {
    let file = File::open(path).map_err(|error| format!("cannot read {label}: {error}"))?;
    serde_json::from_reader(file).map_err(|error| format!("invalid {label}: {error}"))
}

fn write_new_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let bytes =
        serde_json::to_vec(value).map_err(|error| format!("cannot encode data: {error}"))?;
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("cannot create persistent data: {error}"))?;
    file.write_all(&bytes)
        .and_then(|()| file.sync_all())
        .map_err(|error| format!("cannot persist data: {error}"))
}

fn write_json_synced(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let bytes =
        serde_json::to_vec(value).map_err(|error| format!("cannot encode data: {error}"))?;
    write_synced(path, &bytes)
}

fn write_synced(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create storage directory: {error}"))?;
    }
    let mut file = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .map_err(|error| format!("cannot create stored object: {error}"))?;
    file.write_all(bytes)
        .and_then(|()| file.sync_all())
        .map_err(|error| format!("cannot persist stored object: {error}"))
}

fn replace_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let temporary = path.with_extension(format!("tmp-{}", unique_serial()));
    write_json_synced(&temporary, value)?;
    fs::rename(&temporary, path).map_err(|error| format!("cannot replace metadata: {error}"))
}

fn sync_directory(path: &Path) -> Result<(), String> {
    File::open(path)
        .and_then(|directory| directory.sync_all())
        .map_err(|error| format!("cannot sync registry directory: {error}"))
}

fn unique_serial() -> u64 {
    static SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
    SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
}
