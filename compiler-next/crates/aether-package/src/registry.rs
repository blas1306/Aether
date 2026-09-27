//! Productive registry protocol, immutable cache, and materializing provider.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File, OpenOptions};
use std::io::{self, BufReader, Read, Write};
use std::path::{Component, Path, PathBuf};
use std::sync::{Arc, Mutex};

use directories::BaseDirs;
use fs2::FileExt;
use percent_encoding::{AsciiSet, CONTROLS, utf8_percent_encode};
use semver::Version;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::{
    DependencySpec, PackageName, RegistryPackageMetadata, RegistryProvider, RegistryVersion,
    read_manifest, validate_manifest_package,
};

const URL_SEGMENT: &AsciiSet = &CONTROLS
    .add(b' ')
    .add(b'"')
    .add(b'#')
    .add(b'%')
    .add(b'/')
    .add(b':')
    .add(b'<')
    .add(b'>')
    .add(b'?')
    .add(b'[')
    .add(b'\\')
    .add(b']')
    .add(b'^')
    .add(b'`')
    .add(b'{')
    .add(b'|')
    .add(b'}');

const CACHE_SCHEMA: u32 = 1;
static TEMP_SERIAL: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);

/// Whether registry operations may access the network.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RegistryPolicy {
    /// Fetch current registry observations, reusing verified artifacts.
    Online,
    /// Never access the network; require sufficient cached metadata and artifacts.
    Offline,
}

/// Resource limits applied before an artifact can enter the cache.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct CacheLimits {
    /// Maximum archive bytes accepted from either network or cache.
    pub archive_bytes: u64,
    /// Maximum number of regular files in an archive.
    pub files: u64,
    /// Maximum total uncompressed regular-file bytes.
    pub extracted_bytes: u64,
}

impl Default for CacheLimits {
    fn default() -> Self {
        Self {
            archive_bytes: 64 * 1024 * 1024,
            files: 10_000,
            extracted_bytes: 256 * 1024 * 1024,
        }
    }
}

/// Exact V1 wire metadata. Dependencies map package names to V1 requirements.
#[derive(Clone, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub struct RegistryProtocolMetadata {
    /// Exact package name.
    pub name: String,
    /// Exact `SemVer` spelling.
    pub version: String,
    /// Current yank state.
    pub yanked: bool,
    /// `sha256:` followed by 64 lowercase hexadecimal digits.
    pub checksum: String,
    /// Direct registry dependency requirements.
    #[serde(default)]
    pub dependencies: BTreeMap<String, String>,
    /// Exact expected archive byte length.
    pub archive_size: u64,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct VersionsResponse {
    versions: Vec<RegistryVersionWire>,
}

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct RegistryVersionWire {
    version: String,
    yanked: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Cached<T> {
    schema: u32,
    value: T,
}

/// Minimal reusable V1 client. Implementations return complete archive bytes through a reader.
pub trait RegistryClient: Send + Sync {
    /// List versions visible for a package.
    fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String>;
    /// Fetch immutable metadata for one exact version, including yanked versions.
    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryProtocolMetadata, String>;
    /// Open the exact archive associated with the supplied metadata.
    fn archive(&self, metadata: &RegistryProtocolMetadata) -> Result<Box<dyn Read + Send>, String>;
}

/// HTTPS implementation of the V1 registry protocol.
///
/// Endpoints are `GET /v1/packages/{name}/versions`,
/// `GET /v1/packages/{name}/{version}`, and
/// `GET /v1/packages/{name}/{version}/archive?checksum={sha256}`. Redirects are disabled so an
/// origin change cannot silently weaken transport policy.
pub struct HttpsRegistryClient {
    endpoint: String,
    agent: ureq::Agent,
}

impl HttpsRegistryClient {
    /// Construct a client for an explicitly configured physical endpoint.
    pub fn new(endpoint: &str) -> Result<Self, String> {
        let endpoint = endpoint.trim_end_matches('/');
        if !endpoint.starts_with("https://") {
            return Err("registry endpoint must use HTTPS".to_owned());
        }
        let after_scheme = &endpoint[8..];
        if after_scheme.is_empty() || after_scheme.starts_with('/') || after_scheme.contains('@') {
            return Err(
                "registry endpoint must contain a valid origin without credentials".to_owned(),
            );
        }
        let config = ureq::Agent::config_builder().max_redirects(0).build();
        Ok(Self {
            endpoint: endpoint.to_owned(),
            agent: config.into(),
        })
    }

    fn package_url(&self, name: &str) -> String {
        format!(
            "{}/v1/packages/{}",
            self.endpoint,
            utf8_percent_encode(name, URL_SEGMENT)
        )
    }

    fn read_json<T: for<'de> Deserialize<'de>>(&self, url: &str) -> Result<T, String> {
        let response = self
            .agent
            .get(url)
            .call()
            .map_err(|_| "registry request failed".to_owned())?;
        serde_json::from_reader(response.into_body().into_reader())
            .map_err(|error| format!("registry response is invalid: {error}"))
    }
}

impl RegistryClient for HttpsRegistryClient {
    fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        let url = format!("{}/versions", self.package_url(name.as_str()));
        let response: VersionsResponse = self.read_json(&url)?;
        response
            .versions
            .into_iter()
            .map(|item| {
                Version::parse(&item.version).map_err(|error| {
                    format!(
                        "registry returned invalid version `{}`: {error}",
                        item.version
                    )
                })?;
                Ok(RegistryVersion {
                    version: item.version,
                    yanked: item.yanked,
                })
            })
            .collect()
    }

    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryProtocolMetadata, String> {
        let url = format!(
            "{}/{}",
            self.package_url(name.as_str()),
            utf8_percent_encode(&version.to_string(), URL_SEGMENT)
        );
        self.read_json(&url)
    }

    fn archive(&self, metadata: &RegistryProtocolMetadata) -> Result<Box<dyn Read + Send>, String> {
        let url = format!(
            "{}/{}/archive?checksum={}",
            self.package_url(&metadata.name),
            utf8_percent_encode(&metadata.version, URL_SEGMENT),
            utf8_percent_encode(&metadata.checksum, URL_SEGMENT)
        );
        let response = self
            .agent
            .get(&url)
            .call()
            .map_err(|_| "registry archive request failed".to_owned())?;
        Ok(Box::new(response.into_body().into_reader()))
    }
}

/// Global content-addressed package cache.
#[derive(Clone, Debug)]
pub struct RegistryCache {
    root: PathBuf,
    limits: CacheLimits,
}

impl RegistryCache {
    /// Create a cache rooted at an explicit path. Useful for embedding and tests.
    pub fn new(root: PathBuf, limits: CacheLimits) -> Result<Self, String> {
        let cache = Self { root, limits };
        cache.initialize()?;
        Ok(cache)
    }

    /// Create the cache in the operating system's conventional user cache directory.
    pub fn from_os(limits: CacheLimits) -> Result<Self, String> {
        let base =
            BaseDirs::new().ok_or_else(|| "cannot determine OS cache directory".to_owned())?;
        Self::new(base.cache_dir().join("aether"), limits)
    }

    /// Root of this cache; never part of package identity.
    #[must_use]
    pub fn root(&self) -> &Path {
        &self.root
    }

    /// Remove abandoned download/extraction temporaries without touching active digest writers.
    pub fn cleanup_temporaries(&self) -> Result<usize, String> {
        let temporary_root = self.root.join("tmp");
        let mut removed = 0;
        for entry in fs::read_dir(&temporary_root)
            .map_err(|error| format!("cannot inspect cache temporaries: {error}"))?
        {
            let entry =
                entry.map_err(|error| format!("cannot inspect cache temporary: {error}"))?;
            let name = entry.file_name();
            let name = name.to_string_lossy();
            let Some((digest, remainder)) = name.split_once('.') else {
                continue;
            };
            if digest.len() != 64
                || !(remainder.starts_with("download.") || remainder.starts_with("extract."))
            {
                continue;
            }
            let lock_path = temporary_root.join(format!("{digest}.lock"));
            let lock = OpenOptions::new()
                .create(true)
                .truncate(false)
                .read(true)
                .write(true)
                .open(lock_path)
                .map_err(|error| format!("cannot open temporary cleanup lock: {error}"))?;
            if lock.try_lock_exclusive().is_err() {
                continue;
            }
            let path = entry.path();
            if entry
                .file_type()
                .map_err(|error| format!("cannot inspect cache temporary: {error}"))?
                .is_dir()
            {
                fs::remove_dir_all(&path).map_err(|error| {
                    format!(
                        "cannot remove abandoned extraction `{}`: {error}",
                        path.display()
                    )
                })?;
            } else {
                fs::remove_file(&path).map_err(|error| {
                    format!(
                        "cannot remove abandoned download `{}`: {error}",
                        path.display()
                    )
                })?;
            }
            removed += 1;
        }
        Ok(removed)
    }

    fn initialize(&self) -> Result<(), String> {
        for relative in [
            "registry/official/versions",
            "registry/official/metadata",
            "objects/sha256",
            "sources/sha256",
            "tmp",
        ] {
            fs::create_dir_all(self.root.join(relative)).map_err(|error| {
                format!(
                    "cannot create package cache `{}`: {error}",
                    self.root.display()
                )
            })?;
        }
        Ok(())
    }

    fn digest(checksum: &str) -> Result<&str, String> {
        let digest = checksum
            .strip_prefix("sha256:")
            .ok_or_else(|| format!("unsupported checksum `{checksum}`"))?;
        if digest.len() != 64
            || !digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        {
            return Err(format!("invalid SHA-256 checksum `{checksum}`"));
        }
        Ok(digest)
    }

    fn object_path(&self, checksum: &str) -> Result<PathBuf, String> {
        let digest = Self::digest(checksum)?;
        Ok(self
            .root
            .join("objects/sha256")
            .join(&digest[..2])
            .join(digest))
    }

    fn source_path(&self, checksum: &str) -> Result<PathBuf, String> {
        let digest = Self::digest(checksum)?;
        Ok(self
            .root
            .join("sources/sha256")
            .join(&digest[..2])
            .join(digest))
    }

    fn metadata_path(&self, name: &str, version: &str) -> PathBuf {
        self.root
            .join("registry/official/metadata")
            .join(name)
            .join(format!(
                "{}.json",
                utf8_percent_encode(version, URL_SEGMENT)
            ))
    }

    fn versions_path(&self, name: &str) -> PathBuf {
        self.root
            .join("registry/official/versions")
            .join(format!("{name}.json"))
    }

    fn read_cached<T: for<'de> Deserialize<'de>>(path: &Path) -> Result<T, String> {
        let file = File::open(path).map_err(|error| {
            format!(
                "cached registry data `{}` is unavailable: {error}",
                path.display()
            )
        })?;
        let cached: Cached<T> = serde_json::from_reader(BufReader::new(file)).map_err(|error| {
            format!(
                "cached registry data `{}` is corrupt: {error}",
                path.display()
            )
        })?;
        if cached.schema != CACHE_SCHEMA {
            return Err(format!(
                "cached registry data `{}` has unsupported schema",
                path.display()
            ));
        }
        Ok(cached.value)
    }

    fn write_cached<T: Serialize>(path: &Path, value: &T) -> Result<(), String> {
        let bytes = serde_json::to_vec(&Cached {
            schema: CACHE_SCHEMA,
            value,
        })
        .map_err(|error| format!("cannot encode registry cache: {error}"))?;
        atomic_write(path, &bytes)
    }

    fn cached_versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        Self::read_cached(&self.versions_path(name.as_str()))
    }

    fn store_versions(
        &self,
        name: &PackageName,
        versions: &[RegistryVersion],
    ) -> Result<(), String> {
        Self::write_cached(&self.versions_path(name.as_str()), &versions)
    }

    fn cached_metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryProtocolMetadata, String> {
        Self::read_cached(&self.metadata_path(name.as_str(), &version.to_string()))
    }

    fn store_metadata(&self, metadata: &RegistryProtocolMetadata) -> Result<(), String> {
        Self::write_cached(
            &self.metadata_path(&metadata.name, &metadata.version),
            metadata,
        )
    }

    fn materialize(
        &self,
        metadata: &RegistryProtocolMetadata,
        policy: RegistryPolicy,
        client: &dyn RegistryClient,
    ) -> Result<PathBuf, String> {
        validate_protocol_metadata(metadata)?;
        let digest = Self::digest(&metadata.checksum)?;
        let lock_path = self.root.join("tmp").join(format!("{digest}.lock"));
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&lock_path)
            .map_err(|error| format!("cannot open cache writer lock: {error}"))?;
        lock.lock_exclusive()
            .map_err(|error| format!("cannot lock cache writer: {error}"))?;

        let object = self.object_path(&metadata.checksum)?;
        let source = self.source_path(&metadata.checksum)?;
        if source.is_dir() && Self::verify_source(&source, metadata).is_ok() {
            return Ok(source);
        }
        if source.exists() {
            remove_tree(&source).map_err(|error| {
                format!(
                    "cannot replace corrupt cached source `{}`: {error}",
                    source.display()
                )
            })?;
        }

        let object_valid = object.is_file()
            && verify_object(
                &object,
                &metadata.checksum,
                metadata.archive_size,
                self.limits,
            )
            .is_ok();
        if !object_valid {
            if object.exists() {
                fs::remove_file(&object).map_err(|error| {
                    format!(
                        "cannot remove corrupt cached object `{}`: {error}",
                        object.display()
                    )
                })?;
            }
            if policy == RegistryPolicy::Offline {
                return Err(format!(
                    "offline cache is missing verified artifact `{}@{}` ({})",
                    metadata.name, metadata.version, metadata.checksum
                ));
            }
            self.download_object(client, metadata, &object)?;
        }
        self.extract_object(&object, &source, metadata)?;
        Ok(source)
    }

    fn download_object(
        &self,
        client: &dyn RegistryClient,
        metadata: &RegistryProtocolMetadata,
        object: &Path,
    ) -> Result<(), String> {
        let mut input = client.archive(metadata)?;
        let temporary = self.temporary_path("download", Self::digest(&metadata.checksum)?);
        let result = (|| {
            let mut output = OpenOptions::new()
                .create_new(true)
                .write(true)
                .open(&temporary)
                .map_err(|error| format!("cannot create download temporary: {error}"))?;
            let mut hasher = Sha256::new();
            let mut total = 0_u64;
            let mut buffer = vec![0_u8; 32 * 1024];
            loop {
                let count = input
                    .read(&mut buffer)
                    .map_err(|error| format!("registry archive download failed: {error}"))?;
                if count == 0 {
                    break;
                }
                total = total
                    .checked_add(count as u64)
                    .ok_or_else(|| "registry archive size overflow".to_owned())?;
                if total > self.limits.archive_bytes || total > metadata.archive_size {
                    return Err(
                        "registry archive exceeds declared or configured size limit".to_owned()
                    );
                }
                hasher.update(&buffer[..count]);
                output
                    .write_all(&buffer[..count])
                    .map_err(|error| format!("cannot write download temporary: {error}"))?;
            }
            if total != metadata.archive_size {
                return Err(format!(
                    "registry archive was truncated: expected {} bytes, received {total}",
                    metadata.archive_size
                ));
            }
            let observed = format!("sha256:{:x}", hasher.finalize());
            if observed != metadata.checksum {
                return Err(format!(
                    "registry archive checksum mismatch: expected {}, observed {observed}",
                    metadata.checksum
                ));
            }
            output
                .sync_all()
                .map_err(|error| format!("cannot sync download temporary: {error}"))?;
            publish_file(&temporary, object)
        })();
        if result.is_err() {
            let _ = fs::remove_file(&temporary);
        }
        result
    }

    fn extract_object(
        &self,
        object: &Path,
        source: &Path,
        metadata: &RegistryProtocolMetadata,
    ) -> Result<(), String> {
        let temporary = self.temporary_path("extract", Self::digest(&metadata.checksum)?);
        fs::create_dir(&temporary)
            .map_err(|error| format!("cannot create extraction temporary: {error}"))?;
        let result = (|| {
            let file = File::open(object)
                .map_err(|error| format!("cannot open cached object: {error}"))?;
            let mut archive = tar::Archive::new(BufReader::new(file));
            let mut paths = BTreeSet::new();
            let mut files = 0_u64;
            let mut bytes = 0_u64;
            for item in archive
                .entries()
                .map_err(|error| format!("invalid tar archive: {error}"))?
            {
                let mut entry = item.map_err(|error| format!("invalid tar entry: {error}"))?;
                let entry_type = entry.header().entry_type();
                if !(entry_type.is_file() || entry_type.is_dir()) {
                    return Err("archive contains a link, device, or special file".to_owned());
                }
                let raw = entry.path_bytes();
                let raw = std::str::from_utf8(&raw)
                    .map_err(|_| "archive path is not UTF-8".to_owned())?;
                let relative = safe_archive_path(raw)?;
                let normalized = relative.to_string_lossy().replace('\\', "/");
                if !paths.insert(normalized.clone()) {
                    return Err(format!(
                        "archive contains duplicate normalized path `{normalized}`"
                    ));
                }
                if !allowed_archive_path(&relative, entry_type.is_dir()) {
                    return Err(format!("archive path `{normalized}` is not allowed in V1"));
                }
                let destination = temporary.join(&relative);
                if entry_type.is_dir() {
                    fs::create_dir_all(&destination)
                        .map_err(|error| format!("cannot create extracted directory: {error}"))?;
                    continue;
                }
                files += 1;
                bytes = bytes
                    .checked_add(entry.size())
                    .ok_or_else(|| "extracted size overflow".to_owned())?;
                if files > self.limits.files || bytes > self.limits.extracted_bytes {
                    return Err("archive exceeds extraction limits".to_owned());
                }
                if let Some(parent) = destination.parent() {
                    fs::create_dir_all(parent)
                        .map_err(|error| format!("cannot create extracted parent: {error}"))?;
                }
                let mut output = OpenOptions::new()
                    .create_new(true)
                    .write(true)
                    .open(&destination)
                    .map_err(|error| format!("cannot create extracted file: {error}"))?;
                io::copy(&mut entry, &mut output)
                    .map_err(|error| format!("cannot extract archive file: {error}"))?;
                output
                    .sync_all()
                    .map_err(|error| format!("cannot sync extracted file: {error}"))?;
            }
            Self::verify_source(&temporary, metadata)?;
            if let Some(parent) = source.parent() {
                fs::create_dir_all(parent)
                    .map_err(|error| format!("cannot create source CAS directory: {error}"))?;
            }
            fs::rename(&temporary, source)
                .map_err(|error| format!("cannot publish verified source tree: {error}"))?;
            if let Err(error) = make_read_only(source) {
                let _ = remove_tree(source);
                return Err(error);
            }
            Ok(())
        })();
        if result.is_err() {
            let _ = fs::remove_dir_all(&temporary);
        }
        result
    }

    fn verify_source(root: &Path, metadata: &RegistryProtocolMetadata) -> Result<(), String> {
        let manifest_path = root.join("aether.toml");
        if !manifest_path.is_file() {
            return Err("registry archive has no direct aether.toml".to_owned());
        }
        let manifest = read_manifest(&manifest_path)?;
        let package = validate_manifest_package(&manifest)?;
        if package.name.as_str() != metadata.name || package.version.as_str() != metadata.version {
            return Err(format!(
                "archive manifest does not match `{}@{}`",
                metadata.name, metadata.version
            ));
        }
        if manifest.dependencies != protocol_dependencies(metadata)? {
            return Err(format!(
                "archive dependencies do not match registry metadata for `{}@{}`",
                metadata.name, metadata.version
            ));
        }
        Ok(())
    }

    fn temporary_path(&self, kind: &str, digest: &str) -> PathBuf {
        let serial = TEMP_SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        self.root
            .join("tmp")
            .join(format!("{digest}.{kind}.{}.{}", std::process::id(), serial))
    }
}

/// A per-operation snapshot provider backed by a registry client and global CAS.
pub struct RegistrySnapshotProvider {
    client: Arc<dyn RegistryClient>,
    cache: RegistryCache,
    policy: RegistryPolicy,
    versions: Mutex<BTreeMap<String, Vec<RegistryVersion>>>,
    metadata: Mutex<BTreeMap<(String, String), RegistryProtocolMetadata>>,
}

impl RegistrySnapshotProvider {
    /// Begin one logical registry snapshot. The first observation of every key is frozen.
    #[must_use]
    pub fn new(
        client: Arc<dyn RegistryClient>,
        cache: RegistryCache,
        policy: RegistryPolicy,
    ) -> Self {
        Self {
            client,
            cache,
            policy,
            versions: Mutex::new(BTreeMap::new()),
            metadata: Mutex::new(BTreeMap::new()),
        }
    }

    /// Begin an offline snapshot. No network client is constructed or invoked.
    #[must_use]
    pub fn offline(cache: RegistryCache) -> Self {
        Self::new(Arc::new(OfflineClient), cache, RegistryPolicy::Offline)
    }

    fn observe_versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        let mut snapshot = self.versions.lock().map_err(poisoned)?;
        if let Some(value) = snapshot.get(name.as_str()).cloned() {
            return Ok(value);
        }
        let mut value = match self.policy {
            RegistryPolicy::Online => self.client.versions(name).or_else(|network| {
                self.cache
                    .cached_versions(name)
                    .map_err(|cache| format!("{network}; cached fallback failed: {cache}"))
            })?,
            RegistryPolicy::Offline => self.cache.cached_versions(name).map_err(|error| {
                format!(
                    "offline metadata for `{}` is unavailable: {error}",
                    name.as_str()
                )
            })?,
        };
        value.sort_by(|left, right| left.version.cmp(&right.version));
        if self.policy == RegistryPolicy::Online {
            self.cache.store_versions(name, &value)?;
        }
        snapshot.insert(name.as_str().to_owned(), value.clone());
        Ok(value)
    }

    fn observe_metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryProtocolMetadata, String> {
        let key = (name.as_str().to_owned(), version.to_string());
        let mut snapshot = self.metadata.lock().map_err(poisoned)?;
        if let Some(value) = snapshot.get(&key).cloned() {
            return Ok(value);
        }
        let value = match self.policy {
            RegistryPolicy::Online => self.client.metadata(name, version).or_else(|network| {
                self.cache
                    .cached_metadata(name, version)
                    .map_err(|cache| format!("{network}; cached fallback failed: {cache}"))
            })?,
            RegistryPolicy::Offline => {
                self.cache.cached_metadata(name, version).map_err(|error| {
                    format!(
                        "offline exact metadata for `{}@{version}` is unavailable: {error}",
                        name.as_str()
                    )
                })?
            }
        };
        validate_protocol_metadata(&value)?;
        if value.name != name.as_str() || value.version != version.to_string() {
            return Err(format!(
                "registry exact metadata response does not match `{}@{version}`",
                name.as_str()
            ));
        }
        if self.policy == RegistryPolicy::Online {
            self.cache.store_metadata(&value)?;
        }
        snapshot.insert(key, value.clone());
        Ok(value)
    }
}

struct OfflineClient;

impl RegistryClient for OfflineClient {
    fn versions(&self, _name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        Err("internal error: offline policy attempted a network versions request".to_owned())
    }

    fn metadata(
        &self,
        _name: &PackageName,
        _version: &Version,
    ) -> Result<RegistryProtocolMetadata, String> {
        Err("internal error: offline policy attempted a network metadata request".to_owned())
    }

    fn archive(
        &self,
        _metadata: &RegistryProtocolMetadata,
    ) -> Result<Box<dyn Read + Send>, String> {
        Err("internal error: offline policy attempted a network archive request".to_owned())
    }
}

impl RegistryProvider for RegistrySnapshotProvider {
    fn versions(&self, name: &PackageName) -> Result<Vec<RegistryVersion>, String> {
        self.observe_versions(name)
    }

    fn metadata(
        &self,
        name: &PackageName,
        version: &Version,
    ) -> Result<RegistryPackageMetadata, String> {
        let metadata = self.observe_metadata(name, version)?;
        let root = self
            .cache
            .materialize(&metadata, self.policy, self.client.as_ref())?;
        Ok(RegistryPackageMetadata {
            name: metadata.name.clone(),
            version: metadata.version.clone(),
            checksum: metadata.checksum.clone(),
            dependencies: protocol_dependencies(&metadata)?,
            root,
        })
    }
}

fn validate_protocol_metadata(metadata: &RegistryProtocolMetadata) -> Result<(), String> {
    PackageName::new(metadata.name.clone())?;
    Version::parse(&metadata.version)
        .map_err(|error| format!("registry metadata has invalid version: {error}"))?;
    RegistryCache::digest(&metadata.checksum)?;
    if metadata.archive_size == 0 {
        return Err("registry metadata archive_size must be positive".to_owned());
    }
    protocol_dependencies(metadata)?;
    Ok(())
}

fn protocol_dependencies(
    metadata: &RegistryProtocolMetadata,
) -> Result<BTreeMap<String, DependencySpec>, String> {
    metadata
        .dependencies
        .iter()
        .map(|(name, requirement)| {
            PackageName::new(name.clone())?;
            crate::VersionRequirement::parse(requirement)
                .map_err(|error| format!("registry dependency `{name}`: {error}"))?;
            Ok((name.clone(), DependencySpec::Registry(requirement.clone())))
        })
        .collect()
}

fn safe_archive_path(raw: &str) -> Result<PathBuf, String> {
    if raw.is_empty() || raw.contains('\\') || raw.starts_with('/') {
        return Err(format!("unsafe archive path `{raw}`"));
    }
    let path = Path::new(raw);
    let mut clean = PathBuf::new();
    for component in path.components() {
        match component {
            Component::Normal(value) if !value.is_empty() => clean.push(value),
            _ => return Err(format!("unsafe archive path `{raw}`")),
        }
    }
    Ok(clean)
}

fn allowed_archive_path(path: &Path, directory: bool) -> bool {
    if path == Path::new("aether.toml") {
        return !directory;
    }
    let text = path.to_string_lossy();
    if text == "src" {
        return directory;
    }
    if text.starts_with("src/") {
        return directory || path.extension().is_some_and(|extension| extension == "ae");
    }
    if path.components().count() != 1 || directory {
        return false;
    }
    let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
        return false;
    };
    name == "README"
        || name.starts_with("README.")
        || name == "LICENSE"
        || name.starts_with("LICENSE.")
}

fn verify_object(
    path: &Path,
    checksum: &str,
    expected_size: u64,
    limits: CacheLimits,
) -> Result<(), String> {
    let mut file =
        File::open(path).map_err(|error| format!("cannot open cached object: {error}"))?;
    let size = file
        .metadata()
        .map_err(|error| format!("cannot inspect cached object: {error}"))?
        .len();
    if size != expected_size || size > limits.archive_bytes {
        return Err("cached object size does not match metadata".to_owned());
    }
    let mut hasher = Sha256::new();
    io::copy(&mut file, &mut hasher)
        .map_err(|error| format!("cannot hash cached object: {error}"))?;
    let observed = format!("sha256:{:x}", hasher.finalize());
    if observed != checksum {
        return Err("cached object checksum mismatch".to_owned());
    }
    Ok(())
}

fn publish_file(temporary: &Path, destination: &Path) -> Result<(), String> {
    if let Some(parent) = destination.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create object CAS directory: {error}"))?;
    }
    fs::rename(temporary, destination)
        .map_err(|error| format!("cannot publish verified object: {error}"))
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|error| format!("cannot create metadata cache directory: {error}"))?;
    }
    let serial = TEMP_SERIAL.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let temporary = path.with_extension(format!("tmp-{}-{serial}", std::process::id()));
    let result = (|| {
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&temporary)
            .map_err(|error| format!("cannot create metadata cache temporary: {error}"))?;
        file.write_all(bytes)
            .map_err(|error| format!("cannot write metadata cache: {error}"))?;
        file.sync_all()
            .map_err(|error| format!("cannot sync metadata cache: {error}"))?;
        if path.exists() {
            fs::remove_file(path)
                .map_err(|error| format!("cannot replace metadata cache: {error}"))?;
        }
        fs::rename(&temporary, path)
            .map_err(|error| format!("cannot publish metadata cache: {error}"))
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

fn make_read_only(root: &Path) -> Result<(), String> {
    let mut entries = fs::read_dir(root)
        .map_err(|error| format!("cannot inspect source tree permissions: {error}"))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| format!("cannot inspect source tree permissions: {error}"))?;
    entries.sort_by_key(std::fs::DirEntry::file_name);
    for entry in entries {
        let path = entry.path();
        if entry
            .file_type()
            .map_err(|error| format!("cannot inspect source entry: {error}"))?
            .is_dir()
        {
            make_read_only(&path)?;
        }
        let mut permissions = fs::metadata(&path)
            .map_err(|error| format!("cannot inspect source permissions: {error}"))?
            .permissions();
        permissions.set_readonly(true);
        fs::set_permissions(&path, permissions)
            .map_err(|error| format!("cannot make source immutable: {error}"))?;
    }
    let mut permissions = fs::metadata(root)
        .map_err(|error| format!("cannot inspect source permissions: {error}"))?
        .permissions();
    permissions.set_readonly(true);
    fs::set_permissions(root, permissions)
        .map_err(|error| format!("cannot make source immutable: {error}"))
}

fn remove_tree(root: &Path) -> io::Result<()> {
    make_writable(root)?;
    for entry in fs::read_dir(root)? {
        let entry = entry?;
        let path = entry.path();
        if entry.file_type()?.is_dir() {
            remove_tree(&path)?;
        } else {
            make_writable(&path)?;
            fs::remove_file(path)?;
        }
    }
    fs::remove_dir(root)
}

fn make_writable(path: &Path) -> io::Result<()> {
    let mut permissions = fs::metadata(path)?.permissions();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt as _;
        permissions.set_mode(permissions.mode() | 0o700);
    }
    #[cfg(not(unix))]
    permissions.set_readonly(false);
    fs::set_permissions(path, permissions)
}

fn poisoned<T>(_: std::sync::PoisonError<T>) -> String {
    "registry snapshot lock was poisoned".to_owned()
}
