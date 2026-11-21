//! App-local component installation; no Python, shell installer or mutable remote manifest.
use crate::download::{cancelled, client, fetch, hash_file, hash_file_progress};
use crate::component_reader::JoinedFiles;
use sha2::{Digest, Sha256};
use serde::{Deserialize, Serialize};
use std::{collections::{BTreeMap, HashMap, HashSet}, fs::{self, File}, io::{Read, Write}, path::{Path, PathBuf}, sync::{atomic::{AtomicBool, Ordering}, Mutex}, time::UNIX_EPOCH};

#[derive(Clone, Deserialize)]
pub struct Catalogue { pub version: u32, pub components: Vec<Component> }
#[derive(Clone, Deserialize)]
pub struct Component {
    pub id: String, pub label: String, pub version: String, pub required: bool,
    pub roots: Vec<String>, pub files: Vec<Expected>, pub artifacts: Vec<Artifact>,
    pub source: Option<String>, pub note: String,
}
#[derive(Clone, Deserialize, Serialize)]
pub struct Expected { pub path: String, pub size: u64, pub sha256: String }
#[derive(Clone, Deserialize)]
pub struct Artifact {
    pub urls: Vec<String>, pub size: u64, pub sha256: String, pub kind: String,
    pub target: Option<String>, pub mappings: Vec<Mapping>,
    #[serde(default)] pub parts: Vec<Part>,
}
#[derive(Clone, Deserialize)]
pub struct Part { pub urls: Vec<String>, pub size: u64, pub sha256: String }
#[derive(Clone, Deserialize)]
pub struct Mapping { pub entry: String, pub target: String }
#[derive(Clone, Serialize)]
#[serde(rename_all="camelCase")]
pub struct ComponentStatus {
    pub id: String, pub label: String, pub version: String, pub required: bool,
    pub state: String, pub locations: Vec<String>, pub relative_locations: Vec<String>,
    pub installed_bytes: u64, pub download_bytes: Option<u64>, pub source: Option<String>, pub download_sources: Vec<String>,
    pub downloadable: bool, pub message: String,
}
#[derive(Clone, Serialize, Default)]
#[serde(rename_all="camelCase")]
pub struct Transfer {
    pub component_id: String, pub label: String, pub bytes: u64, pub total: u64, pub bytes_per_second: u64,
}
#[derive(Clone, Serialize)]
#[serde(rename_all="camelCase")]
pub struct Snapshot {
    pub version: u32, pub root: String, pub phase: String, pub ready: bool, pub runtime_ready: bool,
    pub active: bool, pub message: String, pub components: Vec<ComponentStatus>, pub transfers: Vec<Transfer>,
    pub gpu: Option<String>,
    pub verification: Option<Verification>,
}
#[derive(Clone, Serialize, Default)]
#[serde(rename_all="camelCase")]
pub struct Verification {
    pub completed: usize, pub total: usize, pub stage: Option<String>,
    pub files_examined: usize, pub files_total: usize, pub bytes_read: u64, pub bytes_total: u64,
}
#[derive(Clone, Deserialize, Serialize, PartialEq)]
struct Stamp { path: String, size: u64, modified: u128 }
#[derive(Deserialize, Serialize, Default)]
struct Checks {
    #[serde(default)] catalogue: String, components: BTreeMap<String, Vec<Stamp>>,
    #[serde(default)] signatures: BTreeMap<String, String>,
}

fn component_signature(component: &Component) -> Result<String, String> {
    use sha2::{Digest, Sha256};
    let contract = serde_json::to_vec(&(&component.version, &component.roots, &component.files)).map_err(|e| e.to_string())?;
    Ok(format!("{:x}", Sha256::digest(contract)))
}
#[derive(Deserialize, Serialize)]
struct Move { path: String, existed: bool }
#[derive(Deserialize, Serialize)]
struct Journal { component: String, committed: bool, moves: Vec<Move> }

pub struct Availability {
    pub active: bool,
    pub ready: bool,
    pub runtime_ready: bool,
}

pub struct Engine {
    pub root: PathBuf, pub catalogue: Catalogue, state: Mutex<Snapshot>,
    operation: Mutex<()>, cancel: AtomicBool,
}

fn atomic_json(path: &Path, value: &impl Serialize) -> Result<(), String> {
    let pending = path.with_extension("pending");
    let mut output = std::io::BufWriter::new(File::create(&pending).map_err(|e| e.to_string())?);
    serde_json::to_writer(&mut output, value).map_err(|e| e.to_string())?;
    output.flush().map_err(|e| e.to_string())?;
    output.get_ref().sync_all().map_err(|e| e.to_string())?;
    drop(output);
    // Windows MoveFileEx supports replacement; std::fs::rename replaces files there too.
    fs::rename(pending, path).map_err(|e| e.to_string())
}

fn relative(value: &str) -> Result<(), String> {
    if value.is_empty() || value.contains(['\\', ':']) || value.starts_with('/') || value.len() > 500 { return Err("Invalid component path".into()); }
    for segment in value.split('/') {
        let upper = segment.split('.').next().unwrap_or("").to_ascii_uppercase();
        if segment.is_empty() || segment == "." || segment == ".." || segment.ends_with(['.', ' ']) || segment.chars().any(|c| c.is_control())
            || ["CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"].contains(&upper.as_str()) {
            return Err("Unsafe component path".into());
        }
    }
    Ok(())
}

fn linked(metadata: &fs::Metadata) -> bool {
    #[cfg(windows)] { use std::os::windows::fs::MetadataExt; metadata.file_attributes() & 0x400 != 0 }
    #[cfg(not(windows))] { metadata.file_type().is_symlink() }
}
/// Check existing ancestors, including junctions; lexical containment alone is insufficient.
pub fn contained(root: &Path, value: &str) -> Result<PathBuf, String> {
    relative(value)?;
    let mut path = root.to_path_buf();
    for segment in value.split('/') {
        path.push(segment);
        match fs::symlink_metadata(&path) {
            Ok(metadata) if linked(&metadata) => return Err("Component paths cannot pass through links or junctions".into()),
            Ok(_) => (),
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => (),
            Err(e) => return Err(e.to_string()),
        }
    }
    Ok(path)
}

fn remove_owned(path: &Path) -> Result<(), String> {
    if !path.exists() { return Ok(()); }
    if fs::symlink_metadata(path).map_err(|e| e.to_string())?.is_dir() { fs::remove_dir_all(path) } else { fs::remove_file(path) }.map_err(|e| e.to_string())
}

impl Engine {
    pub fn new(root: PathBuf) -> Result<Self, String> {
        let bytes = include_bytes!("../engine-catalogue.json.gz");
        let catalogue: Catalogue = serde_json::from_reader(flate2::read::GzDecoder::new(&bytes[..])).map_err(|e| format!("Invalid built-in component catalogue: {e}"))?;
        Self::with_catalogue(root, catalogue)
    }
    fn with_catalogue(root: PathBuf, catalogue: Catalogue) -> Result<Self, String> {
        if catalogue.version != 1 { return Err("Unsupported component catalogue".into()); }
        let mut ids = HashSet::new(); let mut all_files = HashSet::new(); let mut roots: Vec<String> = vec![];
        for c in &catalogue.components {
            if !ids.insert(&c.id) || c.id.is_empty() || !c.id.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'-') || c.files.is_empty() { return Err("Invalid component identifier or inventory".into()); }
            if c.roots.is_empty() { return Err("Component has no installation location".into()); }
            for root in &c.roots {
                relative(root)?;
                if !root.starts_with("runtime/") && !root.starts_with("models/") && root != "vendor" { return Err("Component cannot replace app or user data".into()); }
                let normalized = root.to_ascii_lowercase();
                if roots.iter().any(|r| *r == normalized || r.starts_with(&format!("{normalized}/")) || normalized.starts_with(&format!("{r}/"))) { return Err("Component installation roots overlap".into()); }
                roots.push(normalized);
            }
            for f in &c.files {
                relative(&f.path)?;
                if f.sha256.len() != 64 || !f.sha256.bytes().all(|b| b.is_ascii_hexdigit()) || !all_files.insert(f.path.to_ascii_lowercase())
                    || !c.roots.iter().any(|r| f.path == *r || f.path.starts_with(&format!("{r}/"))) { return Err("Invalid or overlapping component inventory".into()); }
            }
            for a in &c.artifacts {
                if a.size == 0 || a.sha256.len() != 64 || !a.sha256.bytes().all(|b| b.is_ascii_hexdigit()) || !["file", "zip"].contains(&a.kind.as_str()) { return Err("Invalid download artifact".into()); }
                if a.parts.len() > 64 || !a.parts.is_empty() && (a.kind != "zip" || a.parts.iter().try_fold(0u64, |n,p| n.checked_add(p.size)) != Some(a.size) || !a.urls.is_empty()) { return Err("Invalid release parts".into()); }
                for part in &a.parts { if part.size == 0 || part.sha256.len() != 64 || !part.sha256.bytes().all(|b| b.is_ascii_hexdigit()) || part.urls.is_empty() { return Err("Invalid release part".into()); } }
                for url in a.urls.iter().chain(a.parts.iter().flat_map(|p|p.urls.iter())) { let parsed = reqwest::Url::parse(url).map_err(|e| e.to_string())?; if parsed.scheme() != "https" || !parsed.username().is_empty() || parsed.password().is_some() { return Err("Component sources must be HTTPS without credentials".into()); } }
                let mut entries = HashSet::new(); let mut targets = HashSet::new();
                for m in &a.mappings { relative(&m.entry)?; if !entries.insert(m.entry.to_ascii_lowercase()) { return Err("Duplicate archive mapping".into()); } }
                for target in a.target.iter().chain(a.mappings.iter().map(|m| &m.target)) { if !targets.insert(target.to_ascii_lowercase()) || !c.files.iter().any(|f| f.path == *target) { return Err("Download target is outside its component or duplicated".into()); } }
            }
        }
        for p in ["data/engine", "temp/components"] { fs::create_dir_all(contained(&root, p)?).map_err(|e| e.to_string())?; }
        let components = catalogue.components.iter().map(|c| ComponentStatus {
            id: c.id.clone(), label: c.label.clone(), version: c.version.clone(), required: c.required && (Self::smart_fit(&root) || !["wholebody","hands"].contains(&c.id.as_str())), state: "unchecked".into(),
            locations: c.roots.iter().map(|p| root.join(p).to_string_lossy().into_owned()).collect(), relative_locations: c.roots.clone(),
            installed_bytes: c.files.iter().map(|f| f.size).sum(), download_bytes: (!c.artifacts.is_empty()).then(|| c.artifacts.iter().map(|a| a.size).sum()),
            source: c.source.clone(), download_sources: c.artifacts.iter().flat_map(|a|a.urls.iter().chain(a.parts.iter().flat_map(|p|p.urls.iter())).cloned()).collect(), downloadable: !c.artifacts.is_empty() && c.artifacts.iter().all(|a| !a.urls.is_empty() || !a.parts.is_empty()), message: c.note.clone(),
        }).collect();
        let engine = Self { state: Mutex::new(Snapshot { version: 1, root: root.to_string_lossy().into_owned(), phase: "checking".into(), ready: false, runtime_ready: false, active: false, message: "Checking private components".into(), components, transfers: vec![], gpu: None, verification: None }), root, catalogue, operation: Mutex::new(()), cancel: AtomicBool::new(false) };
        engine.recover()?;
        Ok(engine)
    }
    fn smart_fit(root:&Path)->bool {
        fs::read(root.join("data/settings.json")).ok().and_then(|b|serde_json::from_slice::<serde_json::Value>(&b).ok()).is_none_or(|s|s["extractionMethod"]!="pure")
    }
    pub fn configure(&self,emit:&dyn Fn(Snapshot)) {
        let smart=Self::smart_fit(&self.root);
        self.update(emit,|s|{
            for c in &mut s.components {c.required=self.catalogue.components.iter().find(|v|v.id==c.id).is_some_and(|v|v.required)&&(smart||!["wholebody","hands"].contains(&c.id.as_str()));}
            s.ready=s.runtime_ready&&s.gpu.is_some()&&s.components.iter().all(|c|!c.required||c.state=="installed");
            if !s.active {s.phase=if s.ready{"ready"}else{"attention"}.into();s.message=if s.ready{"Engine ready · local processing"}else{"Check components required by the selected extraction method"}.into();}
        });
    }
    pub fn snapshot(&self) -> Snapshot { self.state.lock().unwrap_or_else(|e| e.into_inner()).clone() }
    fn update(&self, emit: &dyn Fn(Snapshot), change: impl FnOnce(&mut Snapshot)) {
        let snapshot = { let mut state = self.state.lock().unwrap_or_else(|e| e.into_inner()); change(&mut state); state.clone() }; emit(snapshot);
    }
    pub fn pause(&self) { self.cancel.store(true, Ordering::Relaxed); }
    pub fn health(&self, gpu: Result<String, String>, emit: &dyn Fn(Snapshot)) {
        self.update(emit, |s| { match gpu { Ok(gpu) => { s.gpu = Some(gpu); s.ready = s.components.iter().all(|c| !c.required || c.state == "installed"); s.phase = if s.ready { "ready" } else { "attention" }.into(); s.message = if s.ready { "Engine ready · local processing" } else { "Install missing extraction components" }.into(); }, Err(e) => { s.gpu = None; s.ready = false; s.phase = "attention".into(); s.message = e; } } });
    }
    pub fn availability(&self) -> Availability {
        let state = self.state.lock().unwrap_or_else(|e| e.into_inner());
        Availability {
            active: state.active,
            ready: state.ready,
            runtime_ready: state.runtime_ready,
        }
    }
    fn component(&self, id: &str) -> Result<&Component, String> { self.catalogue.components.iter().find(|c| c.id == id).ok_or("Unknown component".into()) }
    fn path(&self, file: &Expected) -> Result<PathBuf, String> {
        let target = contained(&self.root, &file.path)?;
        #[cfg(debug_assertions)] {
            if !target.exists() {
                let alternative = match file.path.as_str() {
                    "models/detection/rtmo_body7.onnx" => Some(".tools/rtmo/instance-aware.onnx"),
                    "models/refinement/rtmw-l.onnx" => Some(".tools/refinement/rtmw-l.onnx"),
                    "models/refinement/rtmpose-hand.onnx" => Some(".tools/refinement/rtmpose-hand.onnx"), _ => None,
                };
                if let Some(relative) = alternative { return contained(&self.root, relative); }
            }
        }
        Ok(target)
    }
    fn stamps(&self, component: &Component, progress: &mut dyn FnMut(usize)) -> Result<Vec<Stamp>, String> {
        component.files.iter().enumerate().map(|(index, f)| {
            cancelled(&self.cancel)?;
            let path = self.path(f)?; let m = fs::metadata(&path).map_err(|_| format!("Missing {}", f.path))?;
            if !m.is_file() || m.len() != f.size { return Err(format!("Wrong size: {}", f.path)); }
            let stamp = Stamp { path: path.strip_prefix(&self.root).map_err(|e| e.to_string())?.to_string_lossy().into_owned(), size: m.len(), modified: m.modified().map_err(|e| e.to_string())?.duration_since(UNIX_EPOCH).map_err(|e| e.to_string())?.as_nanos() };
            progress(index + 1);
            Ok(stamp)
        }).collect()
    }
    pub fn verify(&self, force: bool, emit: &dyn Fn(Snapshot)) -> Result<Snapshot, String> {
        self.verify_selected(force, None, emit)
    }
    pub fn verify_browser(&self) -> Result<bool, String> {
        Ok(self.verify_selected(false, Some("browser"), &|_| {})?.components.iter().any(|c| c.id == "browser" && c.state == "installed"))
    }
    fn verify_selected(&self, force: bool, only: Option<&str>, emit: &dyn Fn(Snapshot)) -> Result<Snapshot, String> {
        let _lock = self.operation.try_lock().map_err(|_| "A component task is already running")?;
        self.cancel.store(false, Ordering::Relaxed);
        let result = self.verify_inner(force, only, emit);
        if let Err(e) = &result { self.finish_error(e, emit); }
        result
    }
    fn verify_inner(&self, force: bool, only: Option<&str>, emit: &dyn Fn(Snapshot)) -> Result<Snapshot, String> {
        let total = self.catalogue.components.iter().filter(|c| only.is_none_or(|id| c.id == id)).count();
        self.update(emit, |s| { s.active = true; s.phase = "verifying".into(); s.ready = false; s.transfers.clear(); s.verification = Some(Verification { total, ..Default::default() }); s.message = "Verifying private components".into(); });
        let receipt = contained(&self.root, "data/engine/verification.json")?;
        let mut checks: Checks = fs::read(&receipt).ok().and_then(|v| serde_json::from_slice(&v).ok()).unwrap_or_default();
        use sha2::{Digest, Sha256};
        let signature = format!("{:x}", Sha256::digest(include_bytes!("../engine-catalogue.json.gz")));
        // Migrate an old receipt only when its entire pinned catalogue still matches.
        // New receipts are keyed by each component's file contract, so adding a facial
        // module or changing a source URL cannot invalidate unrelated large runtimes.
        let mut dirty = checks.catalogue != signature;
        let old_component_count = checks.components.len();
        let old_signature_count = checks.signatures.len();
        if !dirty {
            for component in &self.catalogue.components {
                if checks.components.contains_key(&component.id) && !checks.signatures.contains_key(&component.id) {
                    checks.signatures.insert(component.id.clone(), component_signature(component)?);
                    dirty = true;
                }
            }
        } else { checks.components.retain(|id, _| checks.signatures.contains_key(id)); }
        checks.catalogue = signature;
        checks.components.retain(|id, _| self.catalogue.components.iter().any(|c| c.id == *id));
        checks.signatures.retain(|id, _| checks.components.contains_key(id));
        dirty |= checks.components.len() != old_component_count
            || checks.signatures.len() != old_signature_count;
        let mut buffer = vec![0; 1024 * 1024];
        for component in self.catalogue.components.iter().filter(|c| only.is_none_or(|id| c.id == id)) {
            if let Err(e) = cancelled(&self.cancel) { self.finish_error(&e, emit); return Err(e); }
            self.update(emit, |s| { s.message = format!("Checking {}", component.label); s.components.iter_mut().find(|c| c.id == component.id).unwrap().state = "checking".into();
                if let Some(v) = &mut s.verification { v.stage = Some("inventory".into()); v.files_examined = 0; v.files_total = component.files.len(); v.bytes_read = 0; v.bytes_total = component.files.iter().map(|f| f.size).sum(); }
            });
            let mut last_update = std::time::Instant::now();
            let stamps = self.stamps(component, &mut |count| {
                if last_update.elapsed() >= std::time::Duration::from_millis(180) {
                    self.update(emit, |s| { if let Some(v) = &mut s.verification { v.files_examined = count; } }); last_update = std::time::Instant::now();
                }
            });
            cancelled(&self.cancel)?;
            let contract = component_signature(component)?;
            let result = match &stamps {
                Ok(stamps) if !force && checks.signatures.get(&component.id) == Some(&contract) && checks.components.get(&component.id) == Some(stamps) => Ok(()),
                Ok(_) => {
                    self.update(emit, |s| { if let Some(v) = &mut s.verification { v.stage = Some("hashing".into()); v.files_examined = component.files.len(); } });
                    let mut read = 0;
                    component.files.iter().try_for_each(|f| {
                        let digest = hash_file_progress(&self.path(f)?, &self.cancel, &mut buffer, &mut |count| {
                            if last_update.elapsed() >= std::time::Duration::from_millis(180) {
                                self.update(emit, |s| { if let Some(v) = &mut s.verification { v.bytes_read = read + count; } }); last_update = std::time::Instant::now();
                            }
                        })?;
                        read += f.size;
                        if digest == f.sha256 { Ok(()) } else { Err(format!("Checksum mismatch: {}", f.path)) }
                    })
                },
                Err(e) => Err(e.clone()),
            };
            cancelled(&self.cancel)?;
            if let (true, Ok(stamps)) = (result.is_ok(), stamps) {
                if checks.components.get(&component.id) != Some(&stamps)
                    || checks.signatures.get(&component.id) != Some(&contract)
                {
                    checks.components.insert(component.id.clone(), stamps);
                    checks.signatures.insert(component.id.clone(), contract);
                    dirty = true;
                }
            } else {
                dirty |= checks.components.remove(&component.id).is_some();
                dirty |= checks.signatures.remove(&component.id).is_some();
            }
            // Keep completed, verified work across an interrupted launch.
            if dirty {
                atomic_json(&receipt, &checks)?;
                dirty = false;
            }
            self.update(emit, |s| { let c = s.components.iter_mut().find(|c| c.id == component.id).unwrap();
                c.state = if result.is_ok() { "installed" } else if result.as_ref().err().is_some_and(|e| e.starts_with("Missing")) { "missing" } else { "attention" }.into();
                c.message = result.err().unwrap_or_else(|| component.note.clone());
                if c.state == "installed" && component.files.len() == 1 {
                    if let Ok(path) = self.path(&component.files[0]) { c.locations = vec![path.to_string_lossy().into_owned()]; }
                }
                if let Some(progress) = &mut s.verification { progress.completed += 1; progress.stage = None; }
            });
        }
        if dirty {
            atomic_json(&receipt, &checks)?;
        }
        self.update(emit, |s| { s.active = false; s.runtime_ready = s.components.iter().find(|c| c.id == "python").is_some_and(|c| c.state == "installed");
            let complete = s.components.iter().all(|c| !c.required || c.state == "installed"); s.phase = if complete { "booting" } else { "attention" }.into();
            s.message = if complete { "Starting the isolated worker health check" } else { "Install or import missing components" }.into(); });
        Ok(self.snapshot())
    }
    fn finish_error(&self, message: &str, emit: &dyn Fn(Snapshot)) {
        self.update(emit, |s| { s.active = false; s.ready = false; s.phase = "attention".into(); s.message = message.into(); });
    }
    pub fn install(&self, id: &str, source: Option<&Path>, browser_open: bool, emit: &(dyn Fn(Snapshot) + Sync)) -> Result<Snapshot, String> {
        let _lock = self.operation.try_lock().map_err(|_| "A component task is already running")?;
        let component = self.component(id)?;
        if id == "browser" && browser_open { return Err("Close PoseSnap before replacing its browser. Relaunch with --engine-setup to import or repair it in the native setup window.".into()); }
        self.cancel.store(false, Ordering::Relaxed);
        self.update(emit, |s| { s.active = true; s.ready = false; s.phase = "downloading".into(); s.message = format!("Preparing {}", component.label); s.transfers.clear(); s.verification = None; });
        let result = self.install_inner(component, source, emit).and_then(|_| self.verify_inner(false, Some(&component.id), emit));
        if let Err(e) = &result {
            if !self.root.join("data/engine/install-journal.json").exists() { let _ = remove_owned(&contained(&self.root, &format!("temp/components/{}/incoming", component.id))?); }
            self.finish_error(e, emit);
        }
        result
    }
    fn install_inner(&self, component: &Component, source: Option<&Path>, emit: &(dyn Fn(Snapshot) + Sync)) -> Result<(), String> {
        let base = contained(&self.root, &format!("temp/components/{}", component.id))?;
        fs::create_dir_all(&base).map_err(|e| e.to_string())?;
        let stage = base.join("incoming");
        remove_owned(&stage)?; fs::create_dir_all(&stage).map_err(|e| e.to_string())?;
        let expanded: u64 = component.files.iter().map(|f| f.size).sum();
        let downloads: u64 = if source.is_none() { component.artifacts.iter().map(|a| a.size).sum() } else { 0 };
        space(&self.root, expanded.saturating_add(downloads).saturating_add(64 * 1024 * 1024))?;
        if let Some(source) = source {
            self.update(emit, |s| { s.phase = "verifying".into(); s.message = "Importing and checking local component files".into(); });
            if source.is_dir() {
                for f in &component.files {
                    let full = contained(source, &f.path)?;
                    let candidate = if full.is_file() { full } else {
                        let suffix = component.roots.iter().find_map(|r| f.path.strip_prefix(&format!("{r}/"))).unwrap_or(&f.path);
                        let relative = contained(source, suffix)?;
                        if relative.is_file() { relative } else { source.join(Path::new(&f.path).file_name().unwrap()) }
                    };
                    self.copy(&candidate, &contained(&stage, &f.path)?, f.size)?;
                }
            } else if component.files.len() == 1 && fs::metadata(source).map(|m| m.len() == component.files[0].size).unwrap_or(false)
                && hash_file(source, &self.cancel)? == component.files[0].sha256 {
                self.copy(source, &contained(&stage, &component.files[0].path)?, component.files[0].size)?;
            } else {
                let matched = component.artifacts.iter().find(|a| a.kind == "zip" && fs::metadata(source).map(|m| m.len() == a.size).unwrap_or(false));
                if let Some(a) = matched { if hash_file(source, &self.cancel)? != a.sha256 { return Err("Imported archive checksum does not match".into()); } self.extract(source, &stage, component, a)?; }
                else { return Err("Import a component folder, complete PoseSnap folder, or its exact verified archive. This file does not match the catalogue.".into()); }
            }
        } else {
            if component.artifacts.is_empty() { return Err(component.note.clone()); }
            let client = client(false)?;
            // At most two streamed artifact transfers, independent of file size.
            for pair in component.artifacts.chunks(2) {
                let results: Vec<Result<Vec<PathBuf>, String>> = std::thread::scope(|scope| {
                    let handles: Vec<_> = pair.iter().map(|a| { let client = &client; let base = &base;
                        scope.spawn(move || {
                            let single = Part { urls:a.urls.clone(), size:a.size, sha256:a.sha256.clone() };
                            let parts = if a.parts.is_empty() { std::slice::from_ref(&single) } else { &a.parts };
                            let mut files = Vec::new(); let mut completed = 0;
                            for part in parts {
                            let file = contained(base, &format!("{}.partial", part.sha256))?;
                            fetch(client, &part.urls, &file, part.size, &part.sha256, &self.cancel, &|bytes, speed| self.update(emit, |s| {
                                let label = a.target.clone().unwrap_or_else(|| component.label.clone());
                                if let Some(t) = s.transfers.iter_mut().find(|t| t.label == label) { t.bytes = completed+bytes; t.bytes_per_second = speed; }
                                else { s.transfers.push(Transfer { component_id: component.id.clone(), label, bytes:completed+bytes, total: a.size, bytes_per_second: speed }); }
                            }))?; completed += part.size; files.push(file);
                            }
                            if !a.parts.is_empty() {
                                let mut reader = JoinedFiles::open(&files).map_err(|e|e.to_string())?; let mut hash=Sha256::new(); let mut buffer=vec![0;1024*1024];
                                loop { cancelled(&self.cancel)?; let n=reader.read(&mut buffer).map_err(|e|e.to_string())?; if n==0 {break;} hash.update(&buffer[..n]); }
                                if format!("{:x}",hash.finalize()) != a.sha256 {return Err("Release parts do not match the pinned complete artifact".into());}
                            }
                            Ok(files) })
                    }).collect();
                    handles.into_iter().map(|h| h.join().unwrap_or_else(|_| Err("Download task stopped".into()))).collect()
                });
                for (a, result) in pair.iter().zip(results) {
                    let files = result?;
                    self.update(emit, |s| { s.phase = "verifying".into(); s.message = format!("Validating {}", component.label); });
                    if a.kind == "zip" { self.extract_reader(JoinedFiles::open(&files).map_err(|e|e.to_string())?, &stage, component, a)?; }
                    else if files.len()==1 { self.copy(&files[0], &contained(&stage, a.target.as_deref().ok_or("Missing download target")?)?, a.size)?; }
                    else { return Err("Multipart raw files are not supported; use a verified archive".into()); }
                }
            }
        }
        for f in &component.files {
            let file = contained(&stage, &f.path)?;
            if fs::metadata(&file).map(|m| m.len()).ok() != Some(f.size) || hash_file(&file, &self.cancel)? != f.sha256 { return Err(format!("Rejected imported component: {} does not match", f.path)); }
        }
        cancelled(&self.cancel)?;
        self.promote(component, &base, &stage)?;
        remove_owned(&base)?;
        Ok(())
    }
    fn copy(&self, source: &Path, target: &Path, size: u64) -> Result<(), String> {
        if linked(&fs::symlink_metadata(source).map_err(|e| format!("Missing import file {}: {e}", source.display()))?) { return Err("Do not import linked files".into()); }
        fs::create_dir_all(target.parent().unwrap()).map_err(|e| e.to_string())?;
        let mut input = File::open(source).map_err(|e| e.to_string())?; let mut output = File::create(target).map_err(|e| e.to_string())?;
        let mut buffer = vec![0; 256 * 1024]; let mut total = 0;
        loop { cancelled(&self.cancel)?; let n = input.read(&mut buffer).map_err(|e| e.to_string())?; if n == 0 { break; } total += n as u64;
            if total > size { return Err("Import exceeded its expected size".into()); } output.write_all(&buffer[..n]).map_err(|e| e.to_string())?; }
        if total != size { return Err("Imported file is incomplete".into()); } output.sync_all().map_err(|e| e.to_string())
    }
    fn extract(&self, source: &Path, stage: &Path, component: &Component, artifact: &Artifact) -> Result<(), String> {
        self.extract_reader(File::open(source).map_err(|e| e.to_string())?,stage,component,artifact)
    }
    fn extract_reader<R: Read + std::io::Seek>(&self, reader:R, stage: &Path, component: &Component, artifact: &Artifact) -> Result<(), String> {
        let mut archive = zip::ZipArchive::new(reader).map_err(|e| e.to_string())?;
        if archive.len() > 50000 { return Err("Archive has too many entries".into()); }
        let expected_files: HashMap<_, _> = component.files.iter()
            .map(|file| (file.path.as_str(), file))
            .collect();
        let mapped_files: HashMap<_, _> = artifact.mappings.iter()
            .filter_map(|mapping| {
                expected_files.get(mapping.target.as_str())
                    .map(|file| (mapping.entry.as_str(), *file))
            })
            .collect();
        let files = if artifact.mappings.is_empty() { &expected_files } else { &mapped_files };
        let mut buffer = vec![0; 256 * 1024];
        let mut names = HashSet::new();
        let mut found = HashSet::new();
        for index in 0..archive.len() {
            cancelled(&self.cancel)?;
            let mut entry = archive.by_index(index).map_err(|e| e.to_string())?;
            let name = entry.name().trim_end_matches('/'); relative(name)?;
            if !names.insert(name.to_ascii_lowercase()) || entry.unix_mode().is_some_and(|m| m & 0o170000 == 0o120000) { return Err("Archive contains duplicate names or links".into()); }
            if entry.is_dir() { continue; }
            let Some(expected) = files.get(name) else { continue; };
            if entry.size() != expected.size || !found.insert(&expected.path) { return Err("Archive entry size or mapping is invalid".into()); }
            let target = contained(stage, &expected.path)?; fs::create_dir_all(target.parent().unwrap()).map_err(|e| e.to_string())?;
            let mut output = File::create(target).map_err(|e| e.to_string())?;
            let mut total = 0;
            loop { cancelled(&self.cancel)?; let n = entry.read(&mut buffer).map_err(|e| e.to_string())?; if n == 0 { break; } total += n as u64;
                if total > expected.size { return Err("Archive expanded beyond its declared size".into()); } output.write_all(&buffer[..n]).map_err(|e| e.to_string())?; }
            if total != expected.size { return Err("Truncated archive entry".into()); } output.sync_all().map_err(|e| e.to_string())?;
        }
        Ok(())
    }
    fn promote(&self, component: &Component, base: &Path, stage: &Path) -> Result<(), String> {
        let journal_path = contained(&self.root, "data/engine/install-journal.json")?;
        let backup = base.join("rollback"); fs::create_dir_all(&backup).map_err(|e| e.to_string())?;
        let mut journal = Journal { component: component.id.clone(), committed: false, moves: vec![] };
        let result = (|| {
            for path in &component.roots {
                let target = contained(&self.root, path)?; let incoming = contained(stage, path)?; let old = contained(&backup, path)?;
                if !incoming.exists() { return Err("Component stage is incomplete".into()); }
                journal.moves.push(Move { path: path.clone(), existed: target.exists() }); atomic_json(&journal_path, &journal)?;
                fs::create_dir_all(target.parent().unwrap()).map_err(|e| e.to_string())?; fs::create_dir_all(old.parent().unwrap()).map_err(|e| e.to_string())?;
                if target.exists() { fs::rename(&target, &old).map_err(|e| e.to_string())?; }
                fs::rename(incoming, target).map_err(|e| e.to_string())?;
            }
            journal.committed = true; atomic_json(&journal_path, &journal)?;
            remove_owned(&backup)?; fs::remove_file(&journal_path).map_err(|e| e.to_string())?; Ok(())
        })();
        if result.is_err() { self.recover()?; }
        result
    }
    fn recover(&self) -> Result<(), String> {
        let path = contained(&self.root, "data/engine/install-journal.json")?;
        if !path.is_file() { return Ok(()); }
        let journal: Journal = serde_json::from_reader(File::open(&path).map_err(|e| e.to_string())?).map_err(|_| "Cannot read the install recovery journal. Keep the folder and contact support.")?;
        let component = self.component(&journal.component)?;
        let base = contained(&self.root, &format!("temp/components/{}", component.id))?;
        for movement in journal.moves.iter().rev() {
            if !component.roots.contains(&movement.path) { return Err("Invalid install recovery path".into()); }
            let target = contained(&self.root, &movement.path)?;
            let backup = contained(&base.join("rollback"), &movement.path)?;
            let incoming = contained(&base.join("incoming"), &movement.path)?;
            if !journal.committed {
                if backup.exists() { remove_owned(&target)?; fs::rename(backup, target).map_err(|e| e.to_string())?; }
                else if !movement.existed && !incoming.exists() { remove_owned(&target)?; }
            }
        }
        remove_owned(&base)?; fs::remove_file(path).map_err(|e| e.to_string())
    }
}

fn space(root: &Path, needed: u64) -> Result<(), String> {
    #[cfg(windows)] {
        use windows_sys::Win32::Storage::FileSystem::GetDiskFreeSpaceExW;
        let path: Vec<u16> = root.to_string_lossy().encode_utf16().chain(Some(0)).collect(); let mut free = 0;
        if unsafe { GetDiskFreeSpaceExW(path.as_ptr(), &mut free, std::ptr::null_mut(), std::ptr::null_mut()) } == 0 { return Err("Cannot check available disk space".into()); }
        if free < needed { return Err(format!("Not enough space. This task needs approximately {:.1} GB free, including staging.", needed as f64 / 1e9)); }
    }
    #[cfg(not(windows))] { let _ = (root, needed); }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*; use sha2::{Digest, Sha256};
    #[test] fn bundled_catalogue_initializes_without_engines_or_overlapping_roots() {
        let root = tempfile::tempdir().unwrap();
        let engine = Engine::new(root.path().into()).unwrap_or_else(|error| panic!("Bundled startup catalogue is invalid: {error}"));
        let camera = engine.component("camera").unwrap();
        assert!(engine.component("guidance-moge3-model").is_err());
        assert!(engine.component("guidance-moge3-runtime").is_err());
        assert_eq!(camera.roots, vec!["models/camera/model.pt"]);
        assert!(!root.path().join("models").exists());
        assert!(!engine.snapshot().runtime_ready);
    }
    #[test] fn repairing_sibling_model_files_preserves_the_other_component() {
        let root = tempfile::tempdir().unwrap();
        let contents = b"valid";
        let components = [("camera", "models/camera/model.pt"), ("trial", "models/camera/moge3-vitl.pt")].into_iter().map(|(id, path)| {
            fs::create_dir_all(root.path().join("models/camera")).unwrap();
            fs::write(root.path().join(path), contents).unwrap();
            Component { id: id.into(), label: id.into(), version: "1".into(), required: false,
                roots: vec![path.into()], files: vec![Expected { path: path.into(), size: 5, sha256: format!("{:x}", Sha256::digest(contents)) }],
                artifacts: vec![], source: None, note: String::new() }
        }).collect();
        let engine = Engine::with_catalogue(root.path().into(), Catalogue { version: 1, components }).unwrap();
        let source = tempfile::tempdir().unwrap();
        fs::write(source.path().join("model"), contents).unwrap();
        for id in ["camera", "trial"] {
            let result = engine.install(id, Some(&source.path().join("model")), false, &|_| {}).unwrap();
            assert_eq!(result.components.iter().find(|component| component.id == id).unwrap().state, "installed");
            assert_eq!(fs::read(root.path().join("models/camera/model.pt")).unwrap(), contents);
            assert_eq!(fs::read(root.path().join("models/camera/moge3-vitl.pt")).unwrap(), contents);
        }
    }
    #[test] fn extraction_choice_changes_requirements_without_faking_gpu_health() {
        let root=tempfile::tempdir().unwrap();let mut catalogue=fixture(root.path());
        catalogue.components[0].id="wholebody".into();
        let e=Engine::with_catalogue(root.path().into(),catalogue).unwrap();
        fs::write(root.path().join("data/settings.json"),b"{\"extractionMethod\":\"pure\"}").unwrap();
        e.configure(&|_|{});assert!(!e.snapshot().components[0].required);assert!(!e.snapshot().ready);
        e.update(&|_|{},|s|{s.runtime_ready=true;s.gpu=Some("Test GPU".into());s.components[0].state="missing".into();});
        e.configure(&|_|{});assert!(e.snapshot().ready);
        for choice in ["smart","auto"] {
            fs::write(root.path().join("data/settings.json"),format!("{{\"extractionMethod\":\"{choice}\"}}")).unwrap();
            e.configure(&|_|{});assert!(e.snapshot().components[0].required);assert!(!e.snapshot().ready);
        }
        e.health(Err("GPU test failed".into()),&|_|{});
        fs::write(root.path().join("data/settings.json"),b"{\"extractionMethod\":\"pure\"}").unwrap();
        e.configure(&|_|{});assert!(!e.snapshot().ready);
    }
    fn fixture(root: &Path) -> Catalogue {
        let contents = b"valid"; fs::create_dir_all(root.join("models/test")).unwrap(); fs::write(root.join("models/test/file"), contents).unwrap();
        Catalogue { version: 1, components: vec![Component { id: "test".into(), label: "Test".into(), version: "1".into(), required: true, roots: vec!["models/test".into()], files: vec![Expected { path: "models/test/file".into(), size: 5, sha256: format!("{:x}", Sha256::digest(contents)) }], artifacts: vec![], source: None, note: String::new() }] }
    }
    fn second_component(root: &Path) -> Component {
        fs::create_dir_all(root.join("models/second")).unwrap();fs::write(root.join("models/second/file"),b"second").unwrap();
        Component {id:"second".into(),label:"Second".into(),version:"1".into(),required:false,roots:vec!["models/second".into()],
            files:vec![Expected{path:"models/second/file".into(),size:6,sha256:format!("{:x}",Sha256::digest(b"second"))}],artifacts:vec![],source:None,note:String::new()}
    }
    fn multipart_fixture(root:&Path,wrong_complete_digest:bool)->Catalogue {
        use std::io::Cursor;
        let mut catalogue=fixture(root);let mut writer=zip::ZipWriter::new(Cursor::new(Vec::new()));
        writer.start_file("models/test/file",zip::write::SimpleFileOptions::default()).unwrap();writer.write_all(b"fresh").unwrap();
        let bytes=writer.finish().unwrap().into_inner();let mut parts=Vec::new();let cache=root.join("temp/components/test");fs::create_dir_all(&cache).unwrap();
        for chunk in bytes.chunks(29){let sha=format!("{:x}",Sha256::digest(chunk));fs::write(cache.join(format!("{sha}.partial")),chunk).unwrap();parts.push(Part{urls:vec!["https://example.invalid/unused-cached-part".into()],size:chunk.len() as u64,sha256:sha});}
        catalogue.components[0].files[0].sha256=format!("{:x}",Sha256::digest(b"fresh"));
        catalogue.components[0].artifacts=vec![Artifact{urls:vec![],size:bytes.len() as u64,sha256:if wrong_complete_digest{"0".repeat(64)}else{format!("{:x}",Sha256::digest(&bytes))},kind:"zip".into(),target:None,mappings:vec![],parts}];
        catalogue
    }
    #[test] fn multipart_release_installs_from_checked_resume_cache_without_a_joined_copy() {
        let root=tempfile::tempdir().unwrap();let catalogue=multipart_fixture(root.path(),false);let engine=Engine::with_catalogue(root.path().into(),catalogue).unwrap();
        assert!(engine.snapshot().components[0].downloadable);
        assert_eq!(engine.install("test",None,false,&|_|{}).unwrap().components[0].state,"installed");
        assert_eq!(fs::read(root.path().join("models/test/file")).unwrap(),b"fresh");
        assert!(!root.path().join("temp/components/test").exists());
    }
    #[test] fn bad_complete_digest_keeps_old_component_and_resumable_parts() {
        let root=tempfile::tempdir().unwrap();let catalogue=multipart_fixture(root.path(),true);let engine=Engine::with_catalogue(root.path().into(),catalogue).unwrap();
        assert!(engine.install("test",None,false,&|_|{}).err().unwrap().contains("pinned complete artifact"));
        assert_eq!(fs::read(root.path().join("models/test/file")).unwrap(),b"valid");
        assert!(root.path().join("temp/components/test").exists());
    }
    #[test] fn multipart_base_and_runtime_helper_are_verified_before_promotion() {
        let root=tempfile::tempdir().unwrap();let mut catalogue=multipart_fixture(root.path(),false);
        let helper=b"runtime helper";let sha=format!("{:x}",Sha256::digest(helper));let target="models/test/tests/helper.py";
        fs::write(root.path().join(format!("temp/components/test/{sha}.partial")),helper).unwrap();
        catalogue.components[0].files.push(Expected{path:target.into(),size:helper.len() as u64,sha256:sha.clone()});
        catalogue.components[0].artifacts.push(Artifact{urls:vec!["https://example.invalid/cached-helper".into()],size:helper.len() as u64,sha256:sha,kind:"file".into(),target:Some(target.into()),mappings:vec![],parts:vec![]});
        let engine=Engine::with_catalogue(root.path().into(),catalogue).unwrap();
        assert_eq!(engine.install("test",None,false,&|_|{}).unwrap().components[0].state,"installed");
        assert_eq!(fs::read(root.path().join("models/test/file")).unwrap(),b"fresh");
        assert_eq!(fs::read(root.path().join(target)).unwrap(),helper);
    }
    #[test] fn malformed_part_inventory_is_rejected_before_installation() {
        let root=tempfile::tempdir().unwrap();let mut catalogue=multipart_fixture(root.path(),false);
        catalogue.components[0].artifacts[0].parts[0].size+=1;
        assert!(Engine::with_catalogue(root.path().into(),catalogue).is_err());
        let mut catalogue=multipart_fixture(root.path(),false);catalogue.components[0].artifacts[0].parts[0].urls=vec!["https://user:secret@example.invalid/part".into()];
        assert!(Engine::with_catalogue(root.path().into(),catalogue).is_err());
    }
    #[test] fn a_new_component_keeps_unrelated_verified_receipts() {
        let root=tempfile::tempdir().unwrap();let mut catalogue=fixture(root.path());
        Engine::with_catalogue(root.path().into(),catalogue.clone()).unwrap().verify(false,&|_|{}).unwrap();
        catalogue.components.push(second_component(root.path()));
        let engine=Engine::with_catalogue(root.path().into(),catalogue).unwrap();let hashed=Mutex::new(Vec::new());
        engine.verify(false,&|s|{if s.verification.as_ref().is_some_and(|v|v.stage.as_deref()==Some("hashing")){hashed.lock().unwrap().push(s.message);}}).unwrap();
        assert_eq!(*hashed.lock().unwrap(),vec!["Checking Second"]);
    }
    #[test] fn changed_pinned_digest_and_forced_verification_cannot_reuse_cache() {
        let root=tempfile::tempdir().unwrap();let mut catalogue=fixture(root.path());
        let engine=Engine::with_catalogue(root.path().into(),catalogue.clone()).unwrap();engine.verify(false,&|_|{}).unwrap();
        let hashed=Mutex::new(0);engine.verify(true,&|s|{if s.verification.as_ref().is_some_and(|v|v.stage.as_deref()==Some("hashing")){*hashed.lock().unwrap()+=1;}}).unwrap();assert_eq!(*hashed.lock().unwrap(),1);
        catalogue.components[0].files[0].sha256=format!("{:x}",Sha256::digest(b"other"));
        let changed=Engine::with_catalogue(root.path().into(),catalogue).unwrap().verify(false,&|_|{}).unwrap();
        assert_eq!(changed.components[0].state,"attention");assert!(changed.components[0].message.contains("Checksum mismatch"));
    }
    #[test] fn completed_components_survive_a_cancelled_following_check() {
        let root=tempfile::tempdir().unwrap();let mut catalogue=fixture(root.path());catalogue.components.push(second_component(root.path()));
        let engine=Engine::with_catalogue(root.path().into(),catalogue).unwrap();
        assert!(engine.verify(false,&|s|{if s.message=="Checking Second"{engine.pause();}}).is_err());
        let receipt:Checks=serde_json::from_slice(&fs::read(root.path().join("data/engine/verification.json")).unwrap()).unwrap();
        assert!(receipt.components.contains_key("test"));assert!(!receipt.components.contains_key("second"));assert!(!engine.snapshot().active);
        let hashed=Mutex::new(Vec::new());engine.verify(false,&|s|{if s.verification.as_ref().is_some_and(|v|v.stage.as_deref()==Some("hashing")){hashed.lock().unwrap().push(s.message);}}).unwrap();
        assert_eq!(*hashed.lock().unwrap(),vec!["Checking Second"]);
    }
    #[test] fn legacy_receipts_need_their_original_catalogue_signature() {
        let root=tempfile::tempdir().unwrap();let catalogue=fixture(root.path());
        let engine=Engine::with_catalogue(root.path().into(),catalogue.clone()).unwrap();engine.verify(false,&|_|{}).unwrap();
        let path=root.path().join("data/engine/verification.json");let mut receipt:serde_json::Value=serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
        receipt.as_object_mut().unwrap().remove("signatures");atomic_json(&path,&receipt).unwrap();
        let hashed=Mutex::new(0);engine.verify(false,&|s|{if s.verification.as_ref().is_some_and(|v|v.stage.as_deref()==Some("hashing")){*hashed.lock().unwrap()+=1;}}).unwrap();assert_eq!(*hashed.lock().unwrap(),0);
        receipt["catalogue"]=serde_json::json!("old-contract");atomic_json(&path,&receipt).unwrap();
        // A browser-only startup must not accidentally bless unsigned stale receipts
        // for other components when it writes the new global catalogue identifier.
        engine.verify_selected(false,Some("absent"),&|_|{}).unwrap();
        engine.verify(false,&|s|{if s.verification.as_ref().is_some_and(|v|v.stage.as_deref()==Some("hashing")){*hashed.lock().unwrap()+=1;}}).unwrap();assert_eq!(*hashed.lock().unwrap(),1);
    }
    #[test]
    fn verification_leaves_an_equivalent_receipt_in_place() {
        use std::time::Duration;

        let root = tempfile::tempdir().unwrap();
        let catalogue = fixture(root.path());
        let engine = Engine::with_catalogue(root.path().into(), catalogue).unwrap();
        engine.verify(false, &|_| {}).unwrap();
        let receipt = root.path().join("data/engine/verification.json");
        let saved_time = UNIX_EPOCH + Duration::from_secs(1_600_000_000);
        File::options().write(true).open(&receipt).unwrap().set_modified(saved_time).unwrap();
        let installed = fs::read(&receipt).unwrap();

        for force in [false, true] {
            engine.verify(force, &|_| {}).unwrap();
            assert_eq!(fs::metadata(&receipt).unwrap().modified().unwrap(), saved_time);
            assert_eq!(fs::read(&receipt).unwrap(), installed);
        }

        fs::remove_file(root.path().join("models/test/file")).unwrap();
        engine.verify(false, &|_| {}).unwrap();
        assert_ne!(fs::read(&receipt).unwrap(), installed);
    }

    #[test] fn verification_catches_changes_and_missing_files() {
        let root = tempfile::tempdir().unwrap(); let catalog = fixture(root.path()); let e = Engine::with_catalogue(root.path().into(), catalog).unwrap();
        assert_eq!(e.verify(false, &|_| {}).unwrap().components[0].state, "installed");
        fs::write(root.path().join("models/test/file"), b"wrong").unwrap(); assert_eq!(e.verify(true, &|_| {}).unwrap().components[0].state, "attention");
        fs::remove_file(root.path().join("models/test/file")).unwrap(); assert_eq!(e.verify(false, &|_| {}).unwrap().components[0].state, "missing");
    }
    #[test] fn verification_reports_completed_checks_without_claiming_gpu_readiness() {
        let root = tempfile::tempdir().unwrap(); let c = fixture(root.path());
        let e = Engine::with_catalogue(root.path().into(), c).unwrap();
        let events = Mutex::new(Vec::new());
        let result = e.verify(false, &|s| { if let Some(v) = s.verification { events.lock().unwrap().push((v.completed,v.total,s.ready)); } }).unwrap();
        let events = events.into_inner().unwrap();
        assert_eq!(events.first(),Some(&(0,1,false)));
        assert_eq!(events.last(),Some(&(1,1,false)));
        assert!(events.windows(2).all(|w| w[0].0 <= w[1].0));
        assert!(!result.ready);
    }
    #[test] fn import_rejects_corruption_without_replacing_old_files() {
        let root = tempfile::tempdir().unwrap(); let c = fixture(root.path()); let e = Engine::with_catalogue(root.path().into(), c).unwrap();
        let source = tempfile::tempdir().unwrap(); fs::write(source.path().join("file"), b"wrong").unwrap();
        assert!(e.install("test", Some(source.path()), false, &|_| {}).is_err());
        assert_eq!(fs::read(root.path().join("models/test/file")).unwrap(), b"valid");
        fs::write(source.path().join("file"), b"valid").unwrap(); assert_eq!(e.install("test", Some(source.path()), false, &|_| {}).unwrap().components[0].state, "installed");
        assert!(!root.path().join("data/engine/install-journal.json").exists());
    }
    #[test] fn cancelled_import_keeps_the_existing_component() {
        let root=tempfile::tempdir().unwrap(); let c=fixture(root.path()); let e=Engine::with_catalogue(root.path().into(),c).unwrap();
        let source=tempfile::tempdir().unwrap(); fs::write(source.path().join("file"),b"valid").unwrap();
        let result=e.install("test",Some(source.path()),false,&|s|{if s.message=="Importing and checking local component files"{e.pause();}});
        assert!(result.is_err()); assert_eq!(fs::read(root.path().join("models/test/file")).unwrap(),b"valid");
        assert!(!e.snapshot().active); assert!(!root.path().join("temp/components/test/incoming").exists());
    }
    #[cfg(windows)]
    #[test] fn insufficient_space_is_actionable() {
        let root=tempfile::tempdir().unwrap(); assert!(space(root.path(),u64::MAX).unwrap_err().contains("Not enough space"));
    }
    #[test] fn paths_and_busy_tasks_are_rejected() {
        let root = tempfile::tempdir().unwrap(); let c = fixture(root.path()); let e = Engine::with_catalogue(root.path().into(), c).unwrap();
        for path in ["../data/file", "models/../../escape", "C:/outside", "models/file:stream", "models/NUL", "models/x.", "models\\file"] { assert!(contained(root.path(), path).is_err()); }
        let _lock = e.operation.lock().unwrap(); assert!(e.verify(false, &|_| {}).is_err());
        assert!(e.install("test", None, false, &|_| {}).is_err());
    }
    #[test] fn interrupted_promotion_restores_backup() {
        let root = tempfile::tempdir().unwrap(); let c = fixture(root.path()); let e = Engine::with_catalogue(root.path().into(), c.clone()).unwrap();
        let base = root.path().join("temp/components/test"); fs::create_dir_all(base.join("rollback/models")).unwrap();
        fs::rename(root.path().join("models/test"), base.join("rollback/models/test")).unwrap();
        fs::create_dir_all(root.path().join("models/test")).unwrap(); fs::write(root.path().join("models/test/file"), b"wrong").unwrap();
        atomic_json(&root.path().join("data/engine/install-journal.json"), &Journal { component: "test".into(), committed: false, moves: vec![Move { path: "models/test".into(), existed: true }] }).unwrap();
        drop(e); let e = Engine::with_catalogue(root.path().into(), c).unwrap();
        assert_eq!(e.verify(false, &|_| {}).unwrap().components[0].state, "installed");
    }
    fn archive_case(entry: &str, contents: &[u8], target: &str, size: u64) -> (tempfile::TempDir, Engine, PathBuf, Artifact) {
        let root = tempfile::tempdir().unwrap(); let c = fixture(root.path()); let e = Engine::with_catalogue(root.path().into(), c).unwrap();
        let path = root.path().join("fixture.zip");
        let mut archive = zip::ZipWriter::new(File::create(&path).unwrap());
        archive.start_file(entry, zip::write::SimpleFileOptions::default()).unwrap(); archive.write_all(contents).unwrap(); archive.finish().unwrap();
        let artifact = Artifact { urls: vec![], size, sha256: String::new(), kind: "zip".into(), target: None, mappings: vec![Mapping { entry: entry.into(), target: target.into() }], parts:vec![] };
        (root, e, path, artifact)
    }
    #[test] fn archives_reject_traversal_and_expansion_mismatch() {
        for entry in ["../outside", "models/test/file:stream", "C:/outside"] {
            let (root,e,archive,a) = archive_case(entry,b"valid","models/test/file",5);
            assert!(e.extract(&archive,&root.path().join("stage"),&e.catalogue.components[0],&a).is_err());
            assert!(!root.path().join("outside").exists());
        }
        let (root,e,archive,a) = archive_case("payload",b"oversized","models/test/file",9);
        assert!(e.extract(&archive,&root.path().join("stage"),&e.catalogue.components[0],&a).is_err());
    }
    #[test] fn archive_maps_only_declared_files_and_checks_final_digest() {
        let (root,e,archive,a) = archive_case("nested/end2end.onnx",b"valid","models/test/file",5);
        let stage = root.path().join("stage"); e.extract(&archive,&stage,&e.catalogue.components[0],&a).unwrap();
        assert_eq!(fs::read(stage.join("models/test/file")).unwrap(),b"valid");
        assert!(!stage.join("nested").exists());
    }
    #[test] fn catalogue_cannot_target_settings_or_share_component_files() {
        let root = tempfile::tempdir().unwrap(); let mut c = fixture(root.path()); c.components[0].roots = vec!["data/settings.json".into()];
        assert!(Engine::with_catalogue(root.path().into(), c).is_err());
        let mut c = fixture(root.path()); let mut duplicate = c.components[0].clone(); duplicate.id = "other".into(); c.components.push(duplicate);
        assert!(Engine::with_catalogue(root.path().into(),c).is_err());
        let mut c = fixture(root.path()); let mut nested = c.components[0].clone(); nested.id = "nested".into(); nested.roots=vec!["models/test/sub".into()];
        nested.files[0].path="models/test/sub/file".into(); c.components.push(nested);
        assert!(Engine::with_catalogue(root.path().into(),c).is_err());
        let mut c = fixture(root.path()); let digest=c.components[0].files[0].sha256.clone(); c.components[0].files.push(Expected{path:"models/test/FILE".into(),size:5,sha256:digest});
        assert!(Engine::with_catalogue(root.path().into(),c).is_err());
    }
    #[test] fn archives_reject_case_collisions_and_symbolic_links() {
        let root=tempfile::tempdir().unwrap(); let c=fixture(root.path()); let e=Engine::with_catalogue(root.path().into(),c).unwrap();
        let path=root.path().join("duplicate.zip"); let mut writer=zip::ZipWriter::new(File::create(&path).unwrap());
        for name in ["payload","PAYLOAD"] { writer.start_file(name,zip::write::SimpleFileOptions::default()).unwrap(); writer.write_all(b"valid").unwrap(); } writer.finish().unwrap();
        let a=Artifact{urls:vec![],size:0,sha256:String::new(),kind:"zip".into(),target:None,mappings:vec![Mapping{entry:"payload".into(),target:"models/test/file".into()}],parts:vec![]};
        assert!(e.extract(&path,&root.path().join("stage"),&e.catalogue.components[0],&a).is_err());
        let path=root.path().join("link.zip"); let mut writer=zip::ZipWriter::new(File::create(&path).unwrap());
        writer.add_symlink("payload","../../outside",zip::write::SimpleFileOptions::default()).unwrap(); writer.finish().unwrap();
        assert!(e.extract(&path,&root.path().join("stage"),&e.catalogue.components[0],&a).is_err());
    }
    #[test] fn file_changes_invalidate_cached_verification_and_health() {
        let root=tempfile::tempdir().unwrap(); let c=fixture(root.path()); let e=Engine::with_catalogue(root.path().into(),c).unwrap();
        assert_eq!(e.snapshot().components[0].state,"unchecked");
        e.verify(false,&|_|{}).unwrap(); e.health(Ok("Fixture GPU".into()),&|_|{}); assert!(e.snapshot().ready);
        let file=root.path().join("models/test/file");
        // Ensure even coarse timestamp filesystems observe a changed stamp.
        let handle=File::options().write(true).open(&file).unwrap(); handle.set_modified(UNIX_EPOCH+std::time::Duration::from_secs(1)).unwrap(); drop(handle);
        fs::write(file,b"wrong").unwrap();
        let changed=e.verify(false,&|_|{}).unwrap(); assert!(!changed.ready); assert_eq!(changed.components[0].state,"attention");
    }
    #[test] fn ready_needs_health_and_failed_health_is_visible() {
        let root = tempfile::tempdir().unwrap(); let c = fixture(root.path()); let e = Engine::with_catalogue(root.path().into(), c).unwrap();
        assert!(!e.verify(false,&|_|{}).unwrap().ready); e.health(Ok("Fixture GPU".into()),&|_|{}); assert!(e.snapshot().ready);
        e.health(Err("GPU unavailable".into()),&|_|{}); assert!(!e.snapshot().ready); assert_eq!(e.snapshot().message,"GPU unavailable");
    }
    #[test] fn import_works_after_unicode_folder_relocation() {
        let base = tempfile::tempdir().unwrap(); let original = base.path().join("Original"); fs::create_dir(&original).unwrap();
        let c = fixture(&original); let moved = base.path().join("PoseSnap moved — தமிழ்"); fs::rename(&original,&moved).unwrap();
        let e = Engine::with_catalogue(moved.clone(),c).unwrap(); assert_eq!(e.verify(false,&|_|{}).unwrap().components[0].state,"installed");
        let source = base.path().join("file"); fs::write(&source,b"valid").unwrap(); e.install("test",Some(&source),false,&|_|{}).unwrap();
        assert_eq!(fs::read(moved.join("models/test/file")).unwrap(),b"valid");
    }
}
