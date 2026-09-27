//! Deterministic source publication and the authenticated publish transport.

use std::collections::{BTreeMap, BTreeSet};
use std::fs::{self, File};
use std::io::{Cursor, Read};
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::registry::{allowed_archive_path, safe_archive_path};
use crate::{
    DependencySpec, Manifest, PackageName, VersionRequirement, read_manifest,
    validate_manifest_package,
};

/// A complete deterministic V1 source publication.
#[derive(Clone, Debug)]
pub struct Publication {
    /// Validated package name.
    pub name: String,
    /// Exact `SemVer` spelling.
    pub version: String,
    /// Registry dependency constraints copied from the manifest.
    pub dependencies: BTreeMap<String, String>,
    /// Sorted archive file names.
    pub files: Vec<String>,
    /// Exact POSIX tar bytes sent to the registry.
    pub archive: Vec<u8>,
    /// SHA-256 of `archive`, including the algorithm prefix.
    pub checksum: String,
}

/// Independently inspected archive contents.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct PublicationContents {
    /// Validated package name.
    pub name: String,
    /// Exact `SemVer` spelling.
    pub version: String,
    /// Registry dependency constraints from the archived manifest.
    pub dependencies: BTreeMap<String, String>,
    /// Sorted regular-file paths found in the archive.
    pub files: Vec<String>,
}

/// Result returned by the immutable registry publish endpoint.
#[derive(Clone, Copy, Debug, Deserialize, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PublishOutcome {
    /// A new immutable version was created.
    Created,
    /// The exact same immutable version had already been published.
    Identical,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PublishResponse {
    outcome: PublishOutcome,
}

/// Validate a library checkout and build its deterministic V1 tar archive.
pub fn build_publication(root: &Path) -> Result<Publication, String> {
    let root = root
        .canonicalize()
        .map_err(|error| format!("cannot resolve publication root: {error}"))?;
    if !root.is_dir() {
        return Err("publication root is not a directory".to_owned());
    }
    let manifest_path = root.join("aether.toml");
    reject_link(&manifest_path, "publication manifest")?;
    let manifest = read_manifest(&manifest_path)?;
    let package = validate_manifest_package(&manifest)?;
    validate_publish_manifest(&manifest)?;
    let library = root.join("src/lib.ae");
    reject_link(&library, "library entry")?;
    if !library.is_file() {
        return Err("publish requires a library with `src/lib.ae`".to_owned());
    }
    if manifest.application.is_some() || root.join("src/main.ae").exists() {
        return Err("publish V1 supports one library target only".to_owned());
    }

    let mut paths = vec![PathBuf::from("aether.toml")];
    collect_sources(&root, &root.join("src"), &mut paths)?;
    collect_optional_root_files(&root, &mut paths)?;
    paths.sort_by(|left, right| path_text(left).cmp(path_text(right)));
    paths.dedup();

    let mut archive = Vec::new();
    {
        let mut builder = tar::Builder::new(&mut archive);
        builder.mode(tar::HeaderMode::Deterministic);
        for relative in &paths {
            let absolute = root.join(relative);
            reject_link(&absolute, "publication file")?;
            let metadata = fs::metadata(&absolute).map_err(|error| {
                format!(
                    "cannot inspect publication file `{}`: {error}",
                    relative.display()
                )
            })?;
            if !metadata.is_file() {
                return Err(format!(
                    "publication path `{}` is not a regular file",
                    relative.display()
                ));
            }
            let mut input = File::open(&absolute).map_err(|error| {
                format!(
                    "cannot open publication file `{}`: {error}",
                    relative.display()
                )
            })?;
            let mut header = tar::Header::new_ustar();
            header.set_size(metadata.len());
            header.set_mode(0o644);
            header.set_uid(0);
            header.set_gid(0);
            header.set_mtime(0);
            header.set_cksum();
            builder
                .append_data(&mut header, path_text(relative), &mut input)
                .map_err(|error| format!("cannot archive `{}`: {error}", relative.display()))?;
        }
        builder
            .finish()
            .map_err(|error| format!("cannot finish publication archive: {error}"))?;
    }
    let checksum = format!("sha256:{:x}", Sha256::digest(&archive));
    let dependencies = registry_dependencies(&manifest)?;
    let publication = Publication {
        name: package.name.as_str().to_owned(),
        version: package.version.as_str().to_owned(),
        dependencies,
        files: paths
            .iter()
            .map(|path| path_text(path).to_owned())
            .collect(),
        archive,
        checksum,
    };
    let inspected = inspect_publication(&publication.archive, publication.archive.len() as u64)?;
    if inspected.name != publication.name
        || inspected.version != publication.version
        || inspected.dependencies != publication.dependencies
        || inspected.files != publication.files
    {
        return Err("internal error: generated publication did not round-trip".to_owned());
    }
    Ok(publication)
}

/// Revalidate exact archive bytes without trusting client-supplied metadata.
pub fn inspect_publication(
    bytes: &[u8],
    maximum_bytes: u64,
) -> Result<PublicationContents, String> {
    if bytes.is_empty() || bytes.len() as u64 > maximum_bytes {
        return Err("publication archive exceeds the configured size limit".to_owned());
    }
    let mut archive = tar::Archive::new(Cursor::new(bytes));
    let mut files = BTreeMap::<String, Vec<u8>>::new();
    let mut seen = BTreeSet::new();
    let mut expanded = 0_u64;
    for item in archive
        .entries()
        .map_err(|error| format!("invalid publication tar: {error}"))?
    {
        let mut entry = item.map_err(|error| format!("invalid publication entry: {error}"))?;
        let entry_type = entry.header().entry_type();
        if !(entry_type.is_file() || entry_type.is_dir()) {
            return Err("publication archive contains a link or special file".to_owned());
        }
        let raw = entry.path_bytes();
        let raw = std::str::from_utf8(&raw)
            .map_err(|_| "publication archive path is not UTF-8".to_owned())?;
        let relative = safe_archive_path(raw)?;
        if !allowed_archive_path(&relative, entry_type.is_dir()) {
            return Err(format!("publication path `{raw}` is not allowed in V1"));
        }
        let normalized = path_text(&relative).to_owned();
        if !seen.insert(normalized.clone()) {
            return Err(format!("publication archive repeats path `{normalized}`"));
        }
        if entry_type.is_dir() {
            continue;
        }
        expanded = expanded
            .checked_add(entry.size())
            .ok_or_else(|| "publication expanded size overflow".to_owned())?;
        if seen.len() > 10_000 || expanded > 256 * 1024 * 1024 {
            return Err("publication archive exceeds extraction limits".to_owned());
        }
        let mut contents = Vec::new();
        entry
            .read_to_end(&mut contents)
            .map_err(|error| format!("cannot read publication entry: {error}"))?;
        files.insert(normalized, contents);
    }
    let manifest_bytes = files
        .get("aether.toml")
        .ok_or_else(|| "publication archive has no direct `aether.toml`".to_owned())?;
    let manifest_text = std::str::from_utf8(manifest_bytes)
        .map_err(|_| "publication manifest is not UTF-8".to_owned())?;
    let manifest: Manifest = toml::from_str(manifest_text)
        .map_err(|error| format!("invalid archived manifest: {error}"))?;
    let package = validate_manifest_package(&manifest)?;
    validate_publish_manifest(&manifest)?;
    if !files.contains_key("src/lib.ae") {
        return Err("publication archive has no `src/lib.ae`".to_owned());
    }
    let dependencies = registry_dependencies(&manifest)?;
    Ok(PublicationContents {
        name: package.name.as_str().to_owned(),
        version: package.version.as_str().to_owned(),
        dependencies,
        files: files.into_keys().collect(),
    })
}

/// Publish exact archive bytes using a bearer token. The endpoint must be HTTPS.
pub fn publish_publication(
    endpoint: &str,
    token: &str,
    publication: &Publication,
) -> Result<PublishOutcome, String> {
    if token.is_empty() {
        return Err("registry token is empty".to_owned());
    }
    let client = crate::HttpsRegistryClient::new(endpoint)?;
    let url = format!(
        "{}/v1/packages/{}/{}",
        client.endpoint(),
        publication.name,
        publication.version
    );
    let response = client
        .agent()
        .post(&url)
        .header("Authorization", &format!("Bearer {token}"))
        .header("Content-Type", "application/x-tar")
        .header("X-Aether-Checksum", &publication.checksum)
        .send(&publication.archive)
        .map_err(|error| match error {
            ureq::Error::StatusCode(401 | 403) => {
                "registry rejected publication authorization".to_owned()
            }
            ureq::Error::StatusCode(409) => {
                "registry rejected immutable version conflict".to_owned()
            }
            _ => "registry publication request failed".to_owned(),
        })?;
    let body: PublishResponse = serde_json::from_reader(response.into_body().into_reader())
        .map_err(|error| format!("registry publication response is invalid: {error}"))?;
    Ok(body.outcome)
}

fn validate_publish_manifest(manifest: &Manifest) -> Result<(), String> {
    if manifest.application.is_some() {
        return Err("publish V1 does not support an `[application]` target".to_owned());
    }
    registry_dependencies(manifest).map(|_| ())
}

fn registry_dependencies(manifest: &Manifest) -> Result<BTreeMap<String, String>, String> {
    manifest
        .dependencies
        .iter()
        .map(|(name, dependency)| {
            PackageName::new(name.clone())?;
            match dependency {
                DependencySpec::Registry(requirement) => {
                    VersionRequirement::parse(requirement)
                        .map_err(|error| format!("dependency `{name}`: {error}"))?;
                    Ok((name.clone(), requirement.clone()))
                }
                DependencySpec::Path(_) => Err(format!(
                    "published package cannot contain path dependency `{name}`"
                )),
            }
        })
        .collect()
}

fn collect_sources(root: &Path, directory: &Path, output: &mut Vec<PathBuf>) -> Result<(), String> {
    reject_link(directory, "source directory")?;
    let mut entries = fs::read_dir(directory)
        .map_err(|error| format!("cannot scan source directory: {error}"))?
        .collect::<Result<Vec<_>, _>>()
        .map_err(|error| format!("cannot scan source directory: {error}"))?;
    entries.sort_by_key(std::fs::DirEntry::file_name);
    for entry in entries {
        let path = entry.path();
        let metadata = fs::symlink_metadata(&path)
            .map_err(|error| format!("cannot inspect source entry: {error}"))?;
        if metadata.file_type().is_symlink() {
            return Err(format!(
                "publication source `{}` is a symlink",
                path.display()
            ));
        }
        if metadata.is_dir() {
            collect_sources(root, &path, output)?;
        } else if metadata.is_file() && path.extension().is_some_and(|value| value == "ae") {
            let relative = path.strip_prefix(root).expect("descendant").to_path_buf();
            if relative.to_str().is_none() {
                return Err(format!(
                    "publication source path `{}` is not valid UTF-8",
                    path.display()
                ));
            }
            output.push(relative);
        } else if !metadata.is_file() {
            return Err(format!(
                "publication source `{}` is not regular",
                path.display()
            ));
        }
    }
    Ok(())
}

fn collect_optional_root_files(root: &Path, output: &mut Vec<PathBuf>) -> Result<(), String> {
    for entry in
        fs::read_dir(root).map_err(|error| format!("cannot scan publication root: {error}"))?
    {
        let entry = entry.map_err(|error| format!("cannot scan publication root: {error}"))?;
        let name = entry.file_name();
        let Some(name) = name.to_str() else { continue };
        if name == "README"
            || name.starts_with("README.")
            || name == "LICENSE"
            || name.starts_with("LICENSE.")
        {
            reject_link(&entry.path(), "publication file")?;
            if !entry.path().is_file() {
                return Err(format!("publication path `{name}` is not a regular file"));
            }
            output.push(PathBuf::from(name));
        }
    }
    Ok(())
}

fn reject_link(path: &Path, label: &str) -> Result<(), String> {
    let metadata = fs::symlink_metadata(path)
        .map_err(|error| format!("cannot inspect {label} `{}`: {error}", path.display()))?;
    if metadata.file_type().is_symlink() {
        return Err(format!(
            "{label} `{}` must not be a symlink",
            path.display()
        ));
    }
    Ok(())
}

fn path_text(path: &Path) -> &str {
    path.to_str()
        .expect("validated publication paths are UTF-8")
}
