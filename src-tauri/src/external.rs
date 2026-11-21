/// Launch web pages through Windows rather than an unsupported WebView popup.
fn checked_url(value: &str) -> Result<String, String> {
    if value.len()>4096 || value.chars().any(|c|c.is_control()||c=='\\') {
        return Err("Invalid source link".into());
    }
    let url=reqwest::Url::parse(value).map_err(|_|"Invalid source link")?;
    if url.scheme()!="https" || url.host_str().is_none() || !url.username().is_empty() || url.password().is_some() {
        return Err("Source links must be HTTPS pages without credentials".into());
    }
    Ok(url.into())
}

pub fn open(value: &str) -> Result<(), String> {
    let url=checked_url(value)?;
    #[cfg(windows)] {
        #[link(name="shell32")]
        extern "system" {fn ShellExecuteW(window:isize,operation:*const u16,file:*const u16,parameters:*const u16,directory:*const u16,show:i32)->isize;}
        let operation:Vec<u16>="open".encode_utf16().chain(Some(0)).collect();
        let target:Vec<u16>=url.encode_utf16().chain(Some(0)).collect();
        let result=unsafe{ShellExecuteW(0,operation.as_ptr(),target.as_ptr(),std::ptr::null(),std::ptr::null(),1)};
        if result<=32 {return Err("Windows could not open this page. Check your default browser and try again.".into());}
        Ok(())
    }
    #[cfg(not(windows))] {let _=url;Err("Opening the default browser is supported in the Windows app.".into())}
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn accepts_official_pages_and_preserves_revision_paths() {
        for url in ["https://huggingface.co/meghshukla/clue/tree/947d1d25c55837f723f6f1da49336483a032987d","https://github.com/facebookresearch/sam-3d-body","https://sketchfab.com/ComputerCats","https://creativecommons.org/licenses/by/4.0/"] {
            assert_eq!(checked_url(url).unwrap(),url);
        }
    }
    #[test] fn rejects_executables_local_paths_protocols_and_embedded_credentials() {
        for url in ["file:///C:/Windows/notepad.exe","C:\\Windows\\notepad.exe","javascript:alert(1)","data:text/html,test","http://example.com","https://user:password@example.com","https://user@example.com","https://example.com/\0bad","https://example.com\\bad",""] {
            assert!(checked_url(url).is_err(),"{url}");
        }
        assert!(checked_url(&format!("https://example.com/{}","a".repeat(4096))).is_err());
    }
}
