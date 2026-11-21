//! Read-only facial assets. Never expose an arbitrary app path to the webview.
use std::{fs, path::Path};
use tauri::http::Method;

/// Resolve the allowed asset for a GET or HEAD request.
pub fn asset(root: &Path, route: &str, method: &Method) -> Result<(Vec<u8>, &'static str), String> {
    let head = method == Method::HEAD;
    if !head && method != Method::GET {
        return Err("Read-only assets".into());
    }
    let path=route.trim_start_matches('/');
    let (relative,mime)=if path=="model" {
        ("models/expression/face_landmarker.task".to_string(),"application/octet-stream")
    }else if path=="vision_bundle.js" {
        ("runtime/vision/vision_bundle.js".to_string(),"text/javascript")
    }else if let Some(name)=path.strip_prefix("wasm/"){
        if !["vision_wasm_internal.js","vision_wasm_internal.wasm","vision_wasm_module_internal.js","vision_wasm_module_internal.wasm","vision_wasm_nosimd_internal.js","vision_wasm_nosimd_internal.wasm"].contains(&name){return Err("Unknown facial asset".into());}
        (format!("runtime/vision/wasm/{name}"),if name.ends_with(".wasm"){"application/wasm"}else{"text/javascript"})
    }else if let Some(id)=path.strip_prefix("image/"){
        if id.len()!=24||!id.bytes().all(|c|c.is_ascii_hexdigit()&&!c.is_ascii_uppercase()){return Err("Invalid reference identifier".into());}
        (format!("data/history/{id}/source.png"),"image/png")
    }else{return Err("Unknown facial asset".into());};
    let file=crate::engine::contained(root,&relative)?;
    let metadata=fs::metadata(&file).map_err(|_|"Facial asset is missing. Open Engine & downloads.".to_string())?;
    if !metadata.is_file()||metadata.len()>160_000_000{return Err("Invalid facial asset".into());}
    let bytes = if head { Vec::new() } else { fs::read(file).map_err(|e| e.to_string())? };
    Ok((bytes, mime))
}
#[cfg(test)] mod tests{
    use super::*;
    #[test] fn only_known_assets_and_reference_ids_are_readable(){
        let root=tempfile::tempdir().unwrap();
        for path in ["../data/settings.json","image/../../secret","wasm/unknown.js","image/ABCDEF012345678901234567","data/settings.json"]{assert!(asset(root.path(), path, &Method::GET).is_err());}
        let id="0123456789abcdef01234567";fs::create_dir_all(root.path().join(format!("data/history/{id}"))).unwrap();
        fs::write(root.path().join(format!("data/history/{id}/source.png")),b"local").unwrap();
        let route = format!("image/{id}");
        assert_eq!(asset(root.path(), &route, &Method::GET).unwrap(), (b"local".to_vec(), "image/png"));
        assert_eq!(asset(root.path(), &route, &Method::HEAD).unwrap(), (Vec::new(), "image/png"));
        assert!(asset(root.path(), "model", &Method::HEAD).is_err());
        assert!(asset(root.path(), &route, &Method::POST).is_err());
    }
}
