//! Bounded, resumable transfers. The trusted catalogue supplies size and digest.
use reqwest::{blocking::Client, header::{CONTENT_RANGE, RANGE}, StatusCode};
use sha2::{Digest, Sha256};
use std::{fs::{self, File, OpenOptions}, io::{Read, Write}, path::Path, sync::atomic::{AtomicBool, Ordering}, time::{Duration, Instant}};

pub fn cancelled(cancel: &AtomicBool) -> Result<(), String> {
    if cancel.load(Ordering::Relaxed) { Err("Paused. Downloaded bytes are kept for Resume.".into()) } else { Ok(()) }
}

pub fn hash_file(path: &Path, cancel: &AtomicBool) -> Result<String, String> {
    hash_file_progress(path, cancel, &mut vec![0; 1024 * 1024], &mut |_| {})
}

/// The verifier reuses one buffer and reports bytes read without claiming digest acceptance.
pub fn hash_file_progress(path: &Path, cancel: &AtomicBool, buffer: &mut [u8], progress: &mut dyn FnMut(u64)) -> Result<String, String> {
    if buffer.is_empty() { return Err("Checksum buffer is empty".into()); }
    let mut input = File::open(path).map_err(|e| e.to_string())?;
    let mut hash = Sha256::new();
    let mut read = 0;
    loop {
        cancelled(cancel)?;
        let count = input.read(buffer).map_err(|e| e.to_string())?;
        if count == 0 { break; }
        hash.update(&buffer[..count]);
        read += count as u64;
        progress(read);
    }
    Ok(format!("{:x}", hash.finalize()))
}

pub fn client(test_http: bool) -> Result<Client, String> {
    client_with_io_timeout(test_http, Duration::from_secs(20))
}

fn client_with_io_timeout(test_http: bool, timeout: Duration) -> Result<Client, String> {
    let builder = if test_http { Client::builder().no_proxy() } else { Client::builder() };
    // reqwest's blocking timeout bounds individual send/read operations. It is
    // not a whole-file deadline; progressing multi-gigabyte transfers may run longer.
    builder.https_only(!test_http).connect_timeout(Duration::from_secs(15))
        .timeout(timeout).redirect(reqwest::redirect::Policy::limited(8))
        .user_agent("PoseSnap/1.0 component-download").build().map_err(|e| e.to_string())
}

fn range_start(value: &str, offset: u64, size: u64) -> bool {
    let Some(value) = value.strip_prefix("bytes ") else { return false; };
    let Some((bounds, total)) = value.split_once('/') else { return false; };
    let Some((start, end)) = bounds.split_once('-') else { return false; };
    start.parse::<u64>().ok() == Some(offset) && total.parse::<u64>().ok() == Some(size)
        && end.parse::<u64>().ok() == size.checked_sub(1)
}

/// Each retry reads the current partial length, including bytes received before a disconnect.
pub fn fetch(client: &Client, urls: &[String], path: &Path, size: u64, digest: &str, cancel: &AtomicBool,
             progress: &(dyn Fn(u64, u64) + Sync)) -> Result<(), String> {
    if urls.is_empty() { return Err("No compatible download source is configured. Use Import from disk.".into()); }
    let mut last = "Download unavailable".to_owned();
    for url in urls {
        for attempt in 0..3 {
            cancelled(cancel)?;
            let start = Instant::now();
            let initial = fs::metadata(path).map(|m| m.len()).unwrap_or(0);
            if initial > size { fs::remove_file(path).map_err(|e| e.to_string())?; }
            let offset = fs::metadata(path).map(|m| m.len()).unwrap_or(0);
            let result = (|| {
                if offset == size && path.is_file() { return Ok(()); }
                let mut request = client.get(url).header("Accept-Encoding", "identity");
                if offset > 0 { request = request.header(RANGE, format!("bytes={offset}-")); }
                let mut response = request.send().map_err(|e| format!("Connection failed: {e}"))?;
                if response.status() == StatusCode::UNAUTHORIZED || response.status() == StatusCode::FORBIDDEN {
                    return Err("The source requires authorised access. Accept its terms on the source website, then import the files. PoseSnap does not bypass access controls.".into());
                }
                if !response.status().is_success() { return Err(format!("Source returned HTTP {}", response.status())); }
                let resumed = response.status() == StatusCode::PARTIAL_CONTENT;
                if resumed && !range_start(response.headers().get(CONTENT_RANGE).and_then(|v| v.to_str().ok()).unwrap_or(""), offset, size) {
                    return Err("The server returned an invalid Content-Range. No bytes were appended.".into());
                }
                if !resumed && response.status() != StatusCode::OK { return Err("Unexpected transfer response".into()); }
                let base = if resumed { offset } else { 0 };
                if response.content_length().is_some_and(|length| length != size - base) {
                    return Err("The source returned a different file size. Try another source or import the pinned file.".into());
                }
                let mut output = OpenOptions::new().write(true).create(true).append(resumed).truncate(!resumed).open(path).map_err(|e| e.to_string())?;
                let mut received = base;
                let mut buffer = vec![0; 256 * 1024];
                let mut last_update = Instant::now();
                loop {
                    cancelled(cancel)?;
                    let count = response.read(&mut buffer).map_err(|e| format!("Transfer interrupted: {e}"))?;
                    if count == 0 { break; }
                    received += count as u64;
                    if received > size { return Err("The source exceeded its pinned size".into()); }
                    output.write_all(&buffer[..count]).map_err(|e| format!("Cannot save download: {e}"))?;
                    if last_update.elapsed() >= Duration::from_millis(180) {
                        progress(received, ((received - base) as f64 / start.elapsed().as_secs_f64().max(0.001)) as u64);
                        last_update = Instant::now();
                    }
                }
                output.sync_all().map_err(|e| e.to_string())?;
                progress(received, 0);
                if received != size { return Err("The source closed before the whole file arrived".into()); }
                Ok(())
            })();
            match result {
                Ok(()) => {
                    if hash_file(path, cancel)? == digest { return Ok(()); }
                    fs::remove_file(path).map_err(|e| e.to_string())?;
                    last = "SHA-256 mismatch. Rejected the downloaded file.".into();
                }
                Err(error) => { last = error; }
            }
            cancelled(cancel)?;
            if attempt < 2 {
                // Short interruptible backoff; cancellation never waits for a long sleep.
                for _ in 0..(5 << attempt) { cancelled(cancel)?; std::thread::sleep(Duration::from_millis(100)); }
            }
        }
    }
    Err(last)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::TcpListener;
    fn hash(bytes: &[u8]) -> String { format!("{:x}", Sha256::digest(bytes)) }
    #[test] fn streamed_checksums_report_reads_and_remain_cancellable() {
        let root=tempfile::tempdir().unwrap();let file=root.path().join("bytes");fs::write(&file,b"0123456789").unwrap();
        let cancel=AtomicBool::new(false);let mut bytes=Vec::new();let mut buffer=[0;4];
        assert_eq!(hash_file_progress(&file,&cancel,&mut buffer,&mut |n|bytes.push(n)).unwrap(),hash(b"0123456789"));assert_eq!(bytes,vec![4,8,10]);
        assert!(hash_file_progress(&file,&cancel,&mut buffer,&mut |_|cancel.store(true,Ordering::Relaxed)).unwrap_err().contains("Paused"));
        assert!(hash_file_progress(&file,&AtomicBool::new(false),&mut [],&mut |_|{}).is_err());
    }
    fn server(reply: &'static str, inspect: impl Fn(String) + Send + 'static) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap(); let addr = listener.local_addr().unwrap();
        std::thread::spawn(move || { let (mut socket, _) = listener.accept().unwrap(); socket.set_read_timeout(Some(Duration::from_secs(2))).unwrap();
            let mut request = [0; 4096]; let n = socket.read(&mut request).unwrap(); inspect(String::from_utf8_lossy(&request[..n]).into());
            socket.write_all(reply.as_bytes()).unwrap(); });
        format!("http://{addr}/file")
    }
    #[test] fn resumes_and_checks_bytes() {
        let dir = tempfile::tempdir().unwrap(); let path = dir.path().join("partial"); fs::write(&path, b"abc").unwrap();
        let url = server("HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 3-5/6\r\nConnection: close\r\n\r\ndef", |r| assert!(r.to_lowercase().contains("range: bytes=3-")));
        fetch(&client(true).unwrap(), &[url], &path, 6, &hash(b"abcdef"), &AtomicBool::new(false), &|_,_|{}).unwrap();
        assert_eq!(fs::read(path).unwrap(), b"abcdef");
    }
    #[test] fn progressing_transfer_can_exceed_the_blocking_io_timeout() {
        let listener=TcpListener::bind("127.0.0.1:0").unwrap();let url=format!("http://{}/file",listener.local_addr().unwrap());
        let sender=std::thread::spawn(move||{
            let (mut socket,_)=listener.accept().unwrap();let mut request=[0;4096];socket.read(&mut request).unwrap();
            socket.write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\n").unwrap();
            for byte in b"abcdef" {std::thread::sleep(Duration::from_millis(120));socket.write_all(&[*byte]).unwrap();socket.flush().unwrap();}
        });
        let root=tempfile::tempdir().unwrap();let target=root.path().join("partial");let started=Instant::now();
        fetch(&client_with_io_timeout(true,Duration::from_millis(400)).unwrap(),&[url],&target,6,&hash(b"abcdef"),&AtomicBool::new(false),&|_,_|{}).unwrap();
        sender.join().unwrap();assert!(started.elapsed()>Duration::from_millis(400));assert_eq!(fs::read(target).unwrap(),b"abcdef");
    }
    #[test] fn ignored_range_restarts_without_appending() {
        let dir = tempfile::tempdir().unwrap(); let path = dir.path().join("partial"); fs::write(&path, b"ab").unwrap();
        let url = server("HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabcdef", |_| {});
        fetch(&client(true).unwrap(), &[url], &path, 6, &hash(b"abcdef"), &AtomicBool::new(false), &|_,_|{}).unwrap();
        assert_eq!(fs::read(path).unwrap(), b"abcdef");
    }
    #[test] fn strict_ranges_and_immediate_pause() {
        assert!(!range_start("bytes 0-2/6", 3, 6)); assert!(!range_start("bytes 3-5/*", 3, 6));
        assert!(cancelled(&AtomicBool::new(true)).is_err());
        assert!(client(false).unwrap().get("http://127.0.0.1/").send().is_err());
    }
    #[test] fn bad_ranges_never_append_and_another_source_can_finish() {
        let dir = tempfile::tempdir().unwrap(); let path = dir.path().join("partial"); fs::write(&path,b"abc").unwrap();
        let bad = server("HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 0-2/6\r\nConnection: close\r\n\r\nxxx", |_| {});
        let good = server("HTTP/1.1 206 Partial Content\r\nContent-Length: 3\r\nContent-Range: bytes 3-5/6\r\nConnection: close\r\n\r\ndef", |_| {});
        fetch(&client(true).unwrap(),&[bad,good],&path,6,&hash(b"abcdef"),&AtomicBool::new(false),&|_,_|{}).unwrap();
        assert_eq!(fs::read(path).unwrap(),b"abcdef");
    }
    #[test] fn checksum_failure_is_rejected_before_mirror_fallback() {
        let dir = tempfile::tempdir().unwrap(); let path = dir.path().join("partial");
        let bad = server("HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nxxxxxx", |_| {});
        let good = server("HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabcdef", |_| {});
        fetch(&client(true).unwrap(),&[bad,good],&path,6,&hash(b"abcdef"),&AtomicBool::new(false),&|_,_|{}).unwrap();
        assert_eq!(fs::read(path).unwrap(),b"abcdef");
    }
    #[test] fn pause_preserves_existing_partial_and_complete_bad_partial_restarts() {
        let dir = tempfile::tempdir().unwrap(); let path = dir.path().join("partial"); fs::write(&path,b"abc").unwrap();
        assert!(fetch(&client(true).unwrap(),&["http://127.0.0.1:1/".into()],&path,6,&hash(b"abcdef"),&AtomicBool::new(true),&|_,_|{}).is_err());
        assert_eq!(fs::read(&path).unwrap(),b"abc");
        fs::write(&path,b"xxxxxx").unwrap();
        let url = server("HTTP/1.1 200 OK\r\nContent-Length: 6\r\nConnection: close\r\n\r\nabcdef", |_| {});
        fetch(&client(true).unwrap(),&[url],&path,6,&hash(b"abcdef"),&AtomicBool::new(false),&|_,_|{}).unwrap();
    }
}
