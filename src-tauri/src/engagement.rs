//! Optional, local creator reminders. Independent of settings and model health.
use serde::{Deserialize, Serialize};
use std::{fs::{self, File, OpenOptions}, path::PathBuf, sync::Mutex, time::{SystemTime, UNIX_EPOCH}};

const GAP_MS: u64 = 10 * 60 * 1000;
const CLOSE_MS: u64 = 5000;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub enum Kind { Welcome, Frequent }

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum Event {
    Workspace,
    Creation { #[serde(rename = "operationId")] operation_id: String, actors: u8 },
    Status,
    Claim,
    Dismiss { #[serde(rename = "claimId")] claim_id: String },
    Disable,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Reply { disabled: bool, pending: Option<Kind>, wait_ms: u64, claim: Option<Claim> }
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Claim { id: String, kind: Kind }

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct Record {
    version: u8, day: String, opens: u8, creations: u8,
    welcome_shown: bool, frequent_shown: bool, disabled: bool,
    not_before_ms: u64, operations: Vec<String>,
}
impl Record {
    fn new(day: &str) -> Self {
        Self { version: 1, day: day.into(), opens: 0, creations: 0, welcome_shown: false,
            frequent_shown: false, disabled: false, not_before_ms: 0, operations: vec![] }
    }
    fn roll(&mut self, day: &str) -> bool {
        // A clock or timezone moving backwards must not repeat today's prompts.
        if day <= self.day.as_str() || self.disabled { return false; }
        let cooldown = self.not_before_ms;
        *self = Self::new(day); self.not_before_ms = cooldown; true
    }
    fn pending(&self) -> Option<Kind> {
        if self.disabled { None }
        else if !self.frequent_shown && (self.opens >= 10 || self.creations >= 10) { Some(Kind::Frequent) }
        else if !self.welcome_shown && self.opens >= 3 { Some(Kind::Welcome) }
        else { None }
    }
    fn valid(&self) -> bool {
        self.version == 1 && self.day.len() == 10 && self.day.bytes().enumerate().all(|(i,c)|
            if i == 4 || i == 7 { c == b'-' } else { c.is_ascii_digit() }) &&
            self.opens <= 10 && self.creations <= 10 && self.operations.len() <= 10 &&
            self.operations.iter().all(|id| valid_id(id))
    }
}
fn valid_id(id: &str) -> bool { (8..=80).contains(&id.len()) && id.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'-') }

#[derive(Default)]
struct Session { opened: bool, dialog: Option<(String, File, u64)> }
pub struct Service { directory: PathBuf, session: Mutex<Session> }
struct Moment { day: String, ms: u64 }
impl Service {
    pub fn new(directory: PathBuf) -> Self { Self { directory, session: Mutex::new(Session::default()) } }
    pub fn event(&self, event: Event) -> Result<Reply, String> { self.at(event, now()?) }
    fn at(&self, event: Event, now: Moment) -> Result<Reply, String> {
        let mut session = self.session.lock().map_err(|_| "Reminder unavailable")?;
        // Holding an exclusive OS file handle serializes updates across launches.
        // Lock contention fails quietly in the caller; normal work never waits.
        let _lock = exclusive(self.directory.join("engagement.lock"))?;
        let path = self.directory.join("engagement.json");
        let mut record = match fs::metadata(&path) {
            Ok(meta) if meta.len() <= 65536 => serde_json::from_slice::<Record>(&fs::read(&path).map_err(|_| "Reminder unavailable")?)
                .ok().filter(Record::valid).ok_or("Reminder unavailable")?,
            Err(e) if e.kind() == std::io::ErrorKind::NotFound => Record::new(&now.day),
            _ => return Err("Reminder unavailable".into()),
        };
        let workspace = matches!(&event, Event::Workspace);
        let mut dismissed = false;
        let mut changed = record.roll(&now.day);
        let mut claim = None;
        match event {
            Event::Disable => {
                record.disabled = true; record.operations.clear(); changed = true;
            }
            Event::Workspace if !session.opened => {
                if !record.disabled { record.opens = (record.opens + 1).min(10); changed = true; }
                // Set only after a successful write so a transient sharing lock
                // can be retried without losing or double-counting this launch.
            }
            Event::Creation { operation_id, actors } => {
                if !valid_id(&operation_id) || !(1..=4).contains(&actors) { return Err("Invalid completion".into()); }
                if !record.disabled && record.creations < 10 && !record.operations.contains(&operation_id) {
                    record.creations = (record.creations + actors).min(10);
                    record.operations.push(operation_id); changed = true;
                }
            }
            Event::Claim if session.opened && session.dialog.is_none() && now.ms >= record.not_before_ms => {
                if let Some(kind) = record.pending() {
                    // Held until dismissal or process exit. A second instance
                    // cannot show a dialog even if the first stays open all day.
                    let dialog = exclusive(self.directory.join("engagement-dialog.lock"))?;
                    let id = format!("{}-{}", std::process::id(), now.ms);
                    match kind { Kind::Welcome => record.welcome_shown = true, Kind::Frequent => record.frequent_shown = true }
                    // If this process dies, the claim stays consumed and a
                    // conservative cooldown survives without an orphan lock.
                    record.not_before_ms = now.ms.saturating_add(GAP_MS + CLOSE_MS);
                    claim = Some((Claim { id: id.clone(), kind }, dialog, now.ms)); changed = true;
                }
            }
            Event::Dismiss { claim_id } => {
                if let Some((id, _, claimed_at)) = &session.dialog {
                    if *id != claim_id || now.ms.saturating_sub(*claimed_at) < CLOSE_MS { return Err("Closing is not available yet".into()); }
                    record.not_before_ms = now.ms.saturating_add(GAP_MS); changed = true;
                    dismissed = true;
                } else { return Err("No active reminder".into()); }
            }
            _ => (),
        }
        if changed {
            let pending = path.with_extension("pending");
            let bytes = serde_json::to_vec(&record).map_err(|_| "Reminder unavailable")?;
            let mut file = File::create(&pending).map_err(|_| "Reminder unavailable")?;
            use std::io::Write;
            file.write_all(&bytes).and_then(|_| file.sync_all()).map_err(|_| "Reminder unavailable")?;
            drop(file); fs::rename(pending, path).map_err(|_| "Reminder unavailable")?;
        }
        // None of these in-memory changes precedes durable persistence.
        // Workspace also handles a disabled installation without writing.
        if workspace { session.opened = true; }
        let active_claim = claim.map(|(value, lock, at)| { session.dialog = Some((value.id.clone(), lock, at)); value });
        if record.disabled || dismissed { session.dialog = None; }
        Ok(Reply { disabled: record.disabled, pending: record.pending(), wait_ms: record.not_before_ms.saturating_sub(now.ms), claim: active_claim })
    }
}

fn exclusive(path: PathBuf) -> Result<File, String> {
    let mut options = OpenOptions::new(); options.read(true).write(true).create(true).truncate(false);
    #[cfg(windows)] { use std::os::windows::fs::OpenOptionsExt; options.share_mode(0); }
    let file = options.open(path).map_err(|_| "Reminder unavailable")?;
    #[cfg(not(windows))] file.try_lock().map_err(|_| "Reminder unavailable")?;
    Ok(file)
}
fn now() -> Result<Moment, String> {
    let ms = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| "Reminder unavailable")?.as_millis() as u64;
    #[cfg(windows)] {
        #[repr(C)] #[derive(Default)] struct SystemTimeLocal { year: u16, month: u16, weekday: u16, day: u16, hour: u16, minute: u16, second: u16, millis: u16 }
        #[link(name = "kernel32")] extern "system" { fn GetLocalTime(time: *mut SystemTimeLocal); }
        let mut time = SystemTimeLocal::default(); unsafe { GetLocalTime(&mut time); }
        Ok(Moment { day: format!("{:04}-{:02}-{:02}", time.year, time.month, time.day), ms })
    }
    #[cfg(not(windows))] { let _ = ms; Err("Local reminder calendar is Windows-only".into()) }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn moment(ms: u64) -> Moment { Moment { day: "2026-10-25".into(), ms } }
    fn send(service: &Service, event: Event, ms: u64) -> Reply { service.at(event, moment(ms)).unwrap() }
    fn creation(id: usize, actors: u8) -> Event { Event::Creation { operation_id: format!("creation-{id:04}"), actors } }
    fn openings(path: &std::path::Path, count: usize) { for _ in 0..count { send(&Service::new(path.into()), Event::Workspace, 1000); } }
    #[test] fn launch_is_once_per_native_session_and_third_open_is_eligible() {
        let root = tempfile::tempdir().unwrap(); let service = Service::new(root.path().into());
        for _ in 0..20 { assert_eq!(send(&service, Event::Workspace, 1000).pending, None); }
        openings(root.path(), 1); assert_eq!(send(&Service::new(root.path().into()), Event::Workspace, 1000).pending, Some(Kind::Welcome));
    }
    #[test] fn frequent_is_one_shared_trigger_and_two_daily_maximum() {
        let root = tempfile::tempdir().unwrap(); openings(root.path(), 9);
        let service = Service::new(root.path().into()); send(&service, Event::Workspace, 1000);
        for i in 0..10 { send(&service, creation(i, 1), 1000); }
        let claim = send(&service, Event::Claim, 1000).claim.unwrap(); assert_eq!(claim.kind, Kind::Frequent);
        assert!(service.at(Event::Dismiss { claim_id: claim.id.clone() }, moment(5999)).is_err());
        send(&service, Event::Dismiss { claim_id: claim.id }, 6000);
        assert!(send(&service, Event::Claim, 605999).claim.is_none());
        let second = send(&service, Event::Claim, 606000).claim.unwrap(); assert_eq!(second.kind, Kind::Welcome);
        send(&service, Event::Dismiss { claim_id: second.id }, 611000);
        assert!(send(&service, Event::Claim, 2000000).claim.is_none());
    }
    #[test] fn actors_count_once_per_completed_batch_not_per_alternative() {
        let root = tempfile::tempdir().unwrap(); let service = Service::new(root.path().into());
        send(&service, Event::Workspace, 1000);
        for i in 0..4 { send(&service, creation(i, 2), 1000); send(&service, creation(i, 2), 1000); }
        assert_eq!(send(&service, creation(4, 1), 1000).pending, None);
        assert_eq!(send(&service, creation(5, 1), 1000).pending, Some(Kind::Frequent));
        assert!(service.at(creation(7, 0), moment(1000)).is_err());
        assert!(service.at(creation(7, 5), moment(1000)).is_err());
    }
    #[test] fn midnight_discards_old_eligibility_but_preserves_cooldown() {
        let root = tempfile::tempdir().unwrap(); openings(root.path(), 3);
        let service = Service::new(root.path().into()); send(&service, Event::Workspace, 1000);
        let claim = send(&service, Event::Claim, 1000).claim.unwrap();
        send(&service, Event::Dismiss { claim_id: claim.id }, 6000);
        let later = |event| service.at(event, Moment { day: "2026-10-26".into(), ms: 10000 }).unwrap();
        let state = later(Event::Status); assert_eq!(state.pending, None); assert_eq!(state.wait_ms, 596000);
        for i in 0..10 { later(creation(i, 1)); }
        assert!(later(Event::Claim).claim.is_none());
        // Changing the clock backwards cannot reset shown flags/counters again.
        assert_eq!(send(&service, Event::Status, 11000).pending, Some(Kind::Frequent));
    }
    #[test] fn permanent_disable_survives_restart_rollover_and_settings_reset() {
        let root = tempfile::tempdir().unwrap(); openings(root.path(), 3);
        let service = Service::new(root.path().into()); send(&service, Event::Disable, 1000);
        let path = root.path().join("engagement.json"); let before = fs::read(&path).unwrap();
        fs::write(root.path().join("settings.json"), b"{}").unwrap();
        let service = Service::new(root.path().into());
        for event in [Event::Workspace, creation(1, 4), Event::Claim] {
            let reply = service.at(event, Moment { day: "2026-10-26".into(), ms: 10000 }).unwrap();
            assert!(reply.disabled); assert!(reply.pending.is_none()); assert!(reply.claim.is_none());
        }
        assert_eq!(fs::read(path).unwrap(), before);
    }
    #[test] fn competing_instances_cannot_claim_while_a_dialog_is_open() {
        let root = tempfile::tempdir().unwrap(); openings(root.path(), 10);
        let first = Service::new(root.path().into()); let second = Service::new(root.path().into());
        send(&first, Event::Workspace, 1000); send(&second, Event::Workspace, 1000);
        let claim = send(&first, Event::Claim, 1000).claim.unwrap();
        assert!(second.at(Event::Claim, moment(1000000)).is_err());
        send(&first, Event::Dismiss { claim_id: claim.id }, 1000000);
        assert!(send(&second, Event::Claim, 1599999).claim.is_none());
        assert_eq!(send(&second, Event::Claim, 1600000).claim.unwrap().kind, Kind::Welcome);
    }
    #[test] fn crash_consumes_claim_and_leaves_no_orphan_os_lock() {
        let root = tempfile::tempdir().unwrap(); openings(root.path(), 10);
        { let service = Service::new(root.path().into()); send(&service, Event::Workspace, 1000); send(&service, Event::Claim, 1000).claim.unwrap(); }
        let service = Service::new(root.path().into()); send(&service, Event::Workspace, 2000);
        assert!(send(&service, Event::Claim, 605999).claim.is_none());
        assert_eq!(send(&service, Event::Claim, 606000).claim.unwrap().kind, Kind::Welcome);
    }
    #[test] fn corrupt_unwritable_or_locked_storage_fails_closed() {
        let root = tempfile::tempdir().unwrap(); let service = Service::new(root.path().into());
        fs::write(root.path().join("engagement.json"), b"{bad").unwrap();
        assert!(service.at(Event::Workspace, moment(1000)).is_err());
        assert_eq!(fs::read(root.path().join("engagement.json")).unwrap(), b"{bad");
        let missing = Service::new(root.path().join("missing")); assert!(missing.at(Event::Claim, moment(1000)).is_err());
        let lock = exclusive(root.path().join("engagement.lock")).unwrap(); assert!(service.at(Event::Status, moment(1000)).is_err()); drop(lock);
    }
    #[test] fn claim_does_not_follow_a_status_read_before_workspace_opens() {
        let root = tempfile::tempdir().unwrap(); openings(root.path(), 3); let service = Service::new(root.path().into());
        send(&service, Event::Status, 1000);
        assert!(send(&service, Event::Claim, 1000).claim.is_none());
    }
}
