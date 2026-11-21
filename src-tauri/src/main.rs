#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
use std::{fs, io::{BufRead, BufReader, BufWriter, Write}, path::{Path, PathBuf}, process::{Child, ChildStdin, ChildStdout, Command, Stdio}, sync::{Arc, Mutex}};
use serde_json::{json, Value};
use tauri::{Emitter, Manager};
mod download;
mod component_reader;
mod engine;
mod face_assets;
mod external;
mod engagement;
#[cfg(windows)] mod bootstrap;
use engine::{Engine, Snapshot};
#[cfg(windows)] use std::os::windows::process::CommandExt;

struct Transport {
    input: BufWriter<ChildStdin>,
    output: BufReader<ChildStdout>,
}

fn reap_child(child: &mut Child) {
    let _ = child.kill();
    let _ = child.wait();
}

fn worker_pipes(mut child: Child) -> Result<(Child, Transport), String> {
    let (Some(input), Some(output)) = (child.stdin.take(), child.stdout.take()) else {
        reap_child(&mut child);
        return Err("Could not open the private worker's pipes. Restart PoseSnap and try again.".into());
    };
    let transport = Transport {
        input: BufWriter::new(input),
        output: BufReader::new(output),
    };
    Ok((child, transport))
}

fn validate_payload(request: &Value) -> Result<(), String> {
    match request.get("payload") {
        None | Some(Value::Null | Value::Object(_)) => Ok(()),
        _ => Err("Expected a worker request payload object".into()),
    }
}

fn exchange_worker(
    input: &mut impl Write,
    output: &mut impl BufRead,
    request: &Value,
    progress: &dyn Fn(&Value),
) -> Result<Value, String> {
    serde_json::to_writer(&mut *input, request).map_err(|e| e.to_string())?;
    input.write_all(b"\n").map_err(|e| e.to_string())?;
    input.flush().map_err(|e| e.to_string())?;

    let mut line = String::new();
    loop {
        line.clear();
        if output.read_line(&mut line).map_err(|e| e.to_string())? == 0 {
            return Err("Worker stopped. The job may have been cancelled; see logs/worker.log.".into());
        }
        let mut event: Value =
            serde_json::from_str(&line).map_err(|_| "Invalid worker response; see local logs")?;
        if event["jobId"] != request["jobId"] {
            continue;
        }
        match event["type"].as_str() {
            Some("progress") => progress(&event),
            Some("error") => {
                return Err(event["message"].as_str().unwrap_or("Processing failed").into());
            }
            Some("result") => return Ok(event.get_mut("result").map_or(Value::Null, Value::take)),
            _ => {}
        }
    }
}
struct Worker { root: PathBuf, child: Mutex<Option<Child>>, transport: Mutex<Option<Transport>>, active: Mutex<Option<String>>, session: Mutex<()> }
impl Worker {
    fn start(&self) -> Result<Transport,String> {
        let python = self.root.join("runtime/python/python.exe");
        if !python.is_file() { return Err("Private Python is missing. Open Settings → Engine & downloads to install or import the engine.".into()); }
        let log_path=self.root.join("logs/worker.log");
        if fs::metadata(&log_path).map(|m|m.len()>5*1024*1024).unwrap_or(false){let previous=self.root.join("logs/worker.previous.log");let _=fs::remove_file(&previous);let _=fs::rename(&log_path,previous);}
        let log = fs::OpenOptions::new().create(true).append(true).open(log_path).map_err(|e|e.to_string())?;
        let mut cmd = Command::new(python);
        cmd.args(["-I", "-B", "-u"]).arg(self.root.join("worker/main.py")).arg("--root").arg(&self.root)
            .current_dir(&self.root).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(log);
        for (k, p) in [("TEMP","temp"),("TMP","temp"),("HF_HOME","data/cache/huggingface"),("TORCH_HOME","data/cache/torch"),("CUDA_CACHE_PATH","data/cache/cuda"),("XDG_CACHE_HOME","data/cache"),("MPLCONFIGDIR","data/cache/matplotlib"),("TRITON_CACHE_DIR","data/cache/triton")] { cmd.env(k,self.root.join(p)); }
        for k in ["PYTHONHOME","PYTHONPATH","PYTHONSTARTUP","PYTHONUSERBASE","VIRTUAL_ENV","CONDA_PREFIX","CUDA_HOME","CUDA_PATH"] { cmd.env_remove(k); }
        cmd.env("PYTHONNOUSERSITE","1").env("HF_HUB_OFFLINE","1").env("TRANSFORMERS_OFFLINE","1").env("MOMENTUM_ENABLED","0").env("OMP_NUM_THREADS","4").env("OPENBLAS_NUM_THREADS","4").env("MKL_NUM_THREADS","4")
            .env("PATH",format!("{};{};{}",self.root.join("runtime/python").display(),self.root.join("runtime/native").display(),std::env::var("SystemRoot").unwrap_or("C:\\Windows".into())+"\\System32"));
        #[cfg(windows)] cmd.creation_flags(0x08000000);
        let mut slot = self.child.lock().map_err(|_| "Worker lock failed")?;
        let child = cmd.spawn().map_err(|e| format!("Could not start private Python: {e}"))?;
        let (child, transport) = worker_pipes(child)?;
        *slot = Some(child);
        Ok(transport)
    }
    fn request(&self, app:&tauri::AppHandle, req:Value) -> Result<Value,String> {
        let _session=self.session.lock().map_err(|_|"Worker session failed")?;
        self.request_locked(app,req)
    }
    fn request_locked(&self, app:&tauri::AppHandle, req:Value) -> Result<Value,String> {
        self.exchange(req,&|event|{let _=app.emit("pose-progress",event);})
    }
    fn exchange(&self, mut req:Value, progress:&dyn Fn(&Value)) -> Result<Value,String> {
        validate_payload(&req)?;
        let mut connection=self.transport.lock().map_err(|_|"Worker transport failed")?;
        let alive=self.child.lock().map_err(|_|"Worker lock failed")?.as_mut().map(|c|c.try_wait().ok().flatten().is_none()).unwrap_or(false);
        if !alive { *connection=Some(self.start()?); }
        req["version"]=json!(1);
        let job=req["jobId"].as_str().ok_or("Missing job identifier")?.to_owned();
        *self.active.lock().map_err(|_|"Worker lock failed")?=Some(job.clone());
        req["payload"]["_jobId"]=json!(job);
        let transport=connection.as_mut().ok_or("Worker unavailable")?;
        let result = exchange_worker(&mut transport.input, &mut transport.output, &req, progress);
        *self.active.lock().map_err(|_|"Worker lock failed")?=None;
        if result.is_err() {
            *connection = None;
            self.reap();
        }
        result
    }
    fn stop(&self) {
        if let Ok(active)=self.active.lock(){if let Some(job)=active.as_ref(){let _=fs::write(self.root.join("temp/jobs").join(format!("{job}.cancel")),b"cancelled");}}
        self.reap();
    }

    fn reap(&self) {
        if let Ok(mut child) = self.child.lock() {
            if let Some(mut child) = child.take() {
                reap_child(&mut child);
            }
        }
    }
}
impl Drop for Worker { fn drop(&mut self){self.stop();} }

#[tauri::command]
async fn request(app:tauri::AppHandle, state:tauri::State<'_,Arc<Worker>>, mut request:Value) -> Result<Value,String> {
    validate_payload(&request)?;
    let method=request["method"].as_str().unwrap_or("");
    if !["status","settings","guidance_inspect","reference_depth","import_image","detect","solve","refine","retarget","history","remove_history","connect_figure","export","apply","read_image","expression_profiles","connect_expression_figure","retarget_expression","save_expression","read_expression","export_expression","apply_expression","zero_expression","text_status","text_load","text_unload","text_kimodo_load","text_kimodo_unload","text_plan","text_generate","text_accept","text_read","text_remove","text_export","text_apply"].contains(&method) { return Err("Unsupported operation".into()); }
    if !request["jobId"].as_str().map(|s|!s.is_empty()&&s.len()<80&&s.bytes().all(|c|c.is_ascii_alphanumeric()||c==b'-')).unwrap_or(false) {return Err("Invalid job identifier".into());}
    let worker=state.inner().clone();
    let engine=app.state::<Arc<Engine>>().inner().clone();
    let availability = engine.availability();
    if availability.active { return Err("Wait for engine verification or installation to finish.".into()); }
    if method=="settings" {
        let saved = local_settings(&worker.root, request["payload"].take())?;
        engine.configure(&|s|{let _=app.emit("engine-status",s);});
        return Ok(saved);
    }
    if !availability.runtime_ready {
        return match method {
            "status" => Ok(local_status(&worker.root, &engine)),
            _ => Err("Private Python is not installed or verified. Open Settings → Engine & downloads.".into()),
        };
    }
    if ["detect","solve","refine"].contains(&method) && !availability.ready { return Err("The extraction engine needs attention. Check Engine & downloads in Settings.".into()); }
    let is_status = method == "status";
    tauri::async_runtime::spawn_blocking(move||{
        let mut result = worker.request(&app, request)?;
        if is_status { result["ready"] = json!(engine.availability().ready); }
        Ok(result)
    }).await.map_err(|e|e.to_string())?
}

fn local_status(root:&Path, engine:&Engine)->Value {
    let state=engine.snapshot();
    let settings=fs::read(root.join("data/settings.json")).ok().and_then(|b|serde_json::from_slice::<Value>(&b).ok()).unwrap_or(json!({}));
    let models:serde_json::Map<String,Value>=state.components.iter().map(|c|(c.id.clone(),json!(c.state=="installed"))).collect();
    let mut response=json!({"version":env!("CARGO_PKG_VERSION"),"root":root,"models":models,"ready":false,"rigs":[],"settings":{"theme":settings["theme"].as_str().unwrap_or("dark"),"motion":settings["motion"].as_str().unwrap_or("auto"),"jointSelector":settings["jointSelector"].as_str().unwrap_or("buttons"),"dazExecutable":settings["dazExecutable"].as_str().unwrap_or(""),"onboarded":settings["onboarded"].as_bool().unwrap_or(false),"refinement":"accurate","extractionMethod":settings["extractionMethod"].as_str().unwrap_or("auto")},"python":"Not installed","offline":true,"refinement":{"available":false,"validated":false}});
    response["settings"]["depthInputType"]=json!(settings["depthInputType"].as_str().filter(|v|["relative","metric"].contains(v)).unwrap_or("relative"));
    response["settings"]["imageGuidance"]=json!(settings["imageGuidance"].as_str().filter(|v|["off","auto"].contains(v)).unwrap_or("auto"));
    for (key,default) in [("textHandShapes",false),("clueEnabled",false),("zeroCroppedJoints",true)]{response["settings"][key]=json!(settings[key].as_bool().unwrap_or(default));}
    response
}
fn startup_preferences(root:&Path)->String {
    let saved=fs::read(root.join("data/settings.json")).ok().and_then(|b|serde_json::from_slice::<Value>(&b).ok()).unwrap_or(json!({}));
    let theme=saved["theme"].as_str().filter(|v|["dark","neon","light"].contains(v)).unwrap_or("dark");
    let motion=saved["motion"].as_str().filter(|v|["auto","reduced"].contains(v)).unwrap_or("auto");
    let extraction=saved["extractionMethod"].as_str().filter(|v|["auto","pure","smart"].contains(v)).unwrap_or("auto");
    let guidance=saved["imageGuidance"].as_str().filter(|v|["off","auto"].contains(v)).unwrap_or("auto");
    format!("window.__POSESNAP_INITIAL_SETTINGS__={};",json!({"theme":theme,"motion":motion,"extractionMethod":extraction,"clueEnabled":saved["clueEnabled"].as_bool().unwrap_or(false),"zeroCroppedJoints":saved["zeroCroppedJoints"].as_bool().unwrap_or(true),"imageGuidance":guidance,"depthInputType":saved["depthInputType"].as_str().filter(|v|["relative","metric"].contains(v)).unwrap_or("relative")}))
}
fn local_settings(root:&Path,payload:Value)->Result<Value,String> {
    let path=root.join("data/settings.json");
    let mut settings=fs::read(&path).ok().and_then(|b|serde_json::from_slice::<Value>(&b).ok()).filter(|v|v.is_object()).unwrap_or(json!({"theme":"dark","motion":"auto","jointSelector":"buttons","dazExecutable":"","onboarded":false}));
    for (key,allowed) in [("theme",vec!["dark","neon","light"]),("motion",vec!["auto","reduced"]),("jointSelector",vec!["buttons","map"]),("extractionMethod",vec!["auto","pure","smart"]),("imageGuidance",vec!["off","auto","detailed"]),("depthInputType",vec!["relative","metric"])] {
        if let Some(value)=payload.get(key) { if !value.as_str().is_some_and(|v|allowed.contains(&v)){return Err(format!("Unknown {key} preference"));} settings[key]=value.clone(); }
    }
    for key in ["dazExecutable","onboarded"] {if let Some(value)=payload.get(key){if key=="dazExecutable"&&!value.is_string()||key=="onboarded"&&!value.is_boolean(){return Err("Invalid preference".into());} settings[key]=value.clone();}}
    for (key,default) in [("textHandShapes",false),("clueEnabled",false),("zeroCroppedJoints",true)] {
        if let Some(value)=payload.get(key){if !value.is_boolean(){return Err(format!("Invalid {key}"));}settings[key]=value.clone();}
        if !settings[key].is_boolean(){settings[key]=json!(default);}
    }
    if !settings["depthInputType"].as_str().is_some_and(|v|["relative","metric"].contains(&v)){settings["depthInputType"]=json!("relative");}
    if !settings["imageGuidance"].as_str().is_some_and(|v|["off","auto"].contains(&v)){settings["imageGuidance"]=json!("auto");}
    // Retired choices cannot be re-enabled through old settings clients.
    for key in ["textPack","textModel","textSpecialist","textDevice","textGpu","textCpuFallback","textVision","textSetupDismissed","textBodyGenerator","geometryEngine"] {settings.as_object_mut().unwrap().remove(key);}
    settings["refinement"]=json!("accurate");
    if settings.get("extractionMethod").is_none(){settings["extractionMethod"]=json!("auto");}
    let pending=path.with_extension("pending");fs::write(&pending,serde_json::to_vec(&settings).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;fs::rename(pending,path).map_err(|e|e.to_string())?;
    Ok(settings)
}
#[tauri::command]
fn engine_status(state:tauri::State<'_,Arc<Engine>>)->Snapshot {state.snapshot()}
#[tauri::command]
fn engine_pause(state:tauri::State<'_,Arc<Engine>>) {state.pause();}
#[tauri::command]
async fn engine_task(app:tauri::AppHandle,state:tauri::State<'_,Arc<Engine>>,worker:tauri::State<'_,Arc<Worker>>,action:String,component_id:Option<String>,source:Option<String>)->Result<Snapshot,String>{
    let engine=state.inner().clone();let worker=worker.inner().clone();
    tauri::async_runtime::spawn_blocking(move||{
        // A transport lock also prevents a job starting midway through installation.
        let guard=worker.session.try_lock().map_err(|_|"Finish the pose task before managing components")?;
        if worker.active.lock().map_err(|_|"Worker lock failed")?.is_some(){return Err("Finish the pose task first".into());}
        worker.stop();
        let emit=|s|{let _=app.emit("engine-status",s);};
        let result=match action.as_str(){
            "check"|"verify"=>engine.verify(action=="verify",&emit),
            "install"=>engine.install(component_id.as_deref().ok_or("Choose a component")?,source.as_deref().map(Path::new),true,&emit),
            _=>Err("Unsupported component task".into()),
        };
        let snapshot=result?;
        if snapshot.runtime_ready {
            let health=worker.request_locked(&app,json!({"jobId":"engine-health","method":"health","payload":{}}))
                .and_then(|v|v["gpu"].as_str().map(str::to_owned).ok_or("No GPU health acknowledgment".into()));
            engine.health(health,&emit);worker.stop();
        }
        drop(guard);
        Ok(engine.snapshot())
    }).await.map_err(|e|e.to_string())?
}
#[tauri::command]
fn cancel(state:tauri::State<'_,Arc<Worker>>) { state.stop(); }
#[tauri::command]
fn open_external_url(url:String)->Result<(),String>{external::open(&url)}
#[tauri::command]
async fn support_event(state:tauri::State<'_,Arc<engagement::Service>>, event:engagement::Event)->Result<engagement::Reply,String>{
    let service=state.inner().clone();
    tauri::async_runtime::spawn_blocking(move||service.event(event)).await.map_err(|_|"Reminder unavailable".to_string())?
}
#[tauri::command]
fn clipboard_image(state:tauri::State<'_,Arc<Worker>>) -> Result<String,String> {
    let mut clipboard=arboard::Clipboard::new().map_err(|e|e.to_string())?;
    let img=clipboard.get_image().map_err(|_|"The clipboard does not contain an image")?;
    let rgba=image::RgbaImage::from_raw(img.width as u32,img.height as u32,img.bytes.into_owned()).ok_or("Invalid clipboard image")?;
    let file=state.root.join("temp/clipboard.png");
    rgba.save(&file).map_err(|e|e.to_string())?;
    Ok(file.to_string_lossy().into())
}
fn portable_root() -> Result<PathBuf, String> {
    #[cfg(debug_assertions)]
    if let Some(root) = std::env::var_os("POSESNAP_DEV_ROOT") {
        return Ok(PathBuf::from(root));
    }
    let executable = std::env::current_exe()
        .map_err(|e| format!("PoseSnap could not locate its executable: {e}"))?;
    executable.parent().map(Path::to_path_buf)
        .ok_or_else(|| "PoseSnap could not locate its portable folder.".into())
}

#[cfg(test)]
mod engine_integration {
    use super::*;

    #[test]
    fn accepts_supported_payload_shapes_without_mutating_requests() {
        for request in [json!({}), json!({"payload":null}), json!({"payload":{}})] {
            assert!(validate_payload(&request).is_ok());
        }
        for payload in [json!(false), json!(7), json!("text"), json!([])] {
            assert!(validate_payload(&json!({"payload":payload})).is_err());
        }
    }

    #[test]
    fn worker_transport_preserves_large_results_and_request_framing() {
        let data = "reference".repeat(120_000);
        let request = json!({"jobId":"extract-one","version":1,"payload":{"preview":data}});
        let replies = format!(
            "{{\"type\":\"result\",\"jobId\":\"old\",\"result\":false}}\n\
             {{\"type\":\"progress\",\"jobId\":\"extract-one\",\"percent\":50}}\n{}\n",
            json!({"type":"result","jobId":"extract-one","result":request["payload"]["preview"]})
        );
        let mut input = Vec::new();
        let mut output = std::io::Cursor::new(replies);
        let progress = std::cell::Cell::new(0);
        let reply = exchange_worker(&mut input, &mut output, &request, &|event| {
            assert_eq!(event["percent"], 50);
            progress.set(progress.get() + 1);
        }).unwrap();
        assert_eq!(progress.get(), 1);
        assert_eq!(reply, request["payload"]["preview"]);
        assert_eq!(input.last(), Some(&b'\n'));
        assert_eq!(serde_json::from_slice::<Value>(&input).unwrap(), request);
    }

    #[test]
    fn worker_transport_distinguishes_worker_errors_and_exit() {
        let request = json!({"jobId":"active"});
        let mut replies = std::io::Cursor::new(
            b"{\"type\":\"error\",\"jobId\":\"active\",\"message\":\"Fixture error\"}\n".as_slice(),
        );
        let mut requests = Vec::new();
        assert_eq!(
            exchange_worker(&mut requests, &mut replies, &request, &|_| {}).unwrap_err(),
            "Fixture error"
        );
        assert!(exchange_worker(&mut requests, &mut replies, &request, &|_| {})
            .unwrap_err().contains("Worker stopped"));
    }

    #[cfg(windows)]
    #[test]
    fn worker_pipe_setup_rejects_missing_pipes() {
        let system = PathBuf::from(std::env::var_os("SystemRoot").expect("Windows system root"));
        let child = Command::new(system.join("System32/cmd.exe"))
            .args(["/d", "/c", "exit", "0"])
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .creation_flags(0x08000000)
            .spawn()
            .expect("start disposable pipe fixture");
        assert!(matches!(worker_pipes(child), Err(message) if message.contains("worker's pipes")));
    }
    #[test]
    fn guidance_preferences_discard_the_retired_engine_selection() {
        let root = tempfile::tempdir().unwrap();
        let data = root.path().join("data");
        fs::create_dir_all(&data).unwrap();
        fs::write(
            data.join("settings.json"),
            br#"{"imageGuidance":"detailed","geometryEngine":"moge3"}"#,
        )
        .unwrap();

        let initial = startup_preferences(root.path());
        assert!(initial.contains("\"imageGuidance\":\"auto\""));
        assert!(!initial.contains("geometryEngine"));
        assert!(local_settings(root.path(), json!({"imageGuidance": true})).is_err());

        let migrated = local_settings(root.path(), json!({})).unwrap();
        assert_eq!(migrated["imageGuidance"], "auto");
        let saved = local_settings(root.path(), json!({"imageGuidance": "off"})).unwrap();
        assert_eq!(saved["imageGuidance"], "off");
        assert!(saved.get("geometryEngine").is_none());
    }

    #[test] fn depth_import_preference_is_validated_and_survives_startup() {
        let root=tempfile::tempdir().unwrap();fs::create_dir_all(root.path().join("data")).unwrap();
        assert!(startup_preferences(root.path()).contains("\"depthInputType\":\"relative\""));
        let saved=local_settings(root.path(),json!({"depthInputType":"metric"})).unwrap();
        assert_eq!(saved["depthInputType"],"metric");
        assert!(startup_preferences(root.path()).contains("\"depthInputType\":\"metric\""));
        assert!(local_settings(root.path(),json!({"depthInputType":"guessed"})).is_err());
    }
    #[test] fn startup_theme_is_validated_before_frontend_mount() {
        let root=tempfile::tempdir().unwrap();fs::create_dir_all(root.path().join("data")).unwrap();
        fs::write(root.path().join("data/settings.json"),br#"{"theme":"neon","motion":"reduced","extractionMethod":"pure"}"#).unwrap();
        let script=startup_preferences(root.path());assert!(script.contains("\"theme\":\"neon\""));assert!(script.contains("\"extractionMethod\":\"pure\""));
        fs::write(root.path().join("data/settings.json"),br#"{"theme":"<script>","dazExecutable":"secret"}"#).unwrap();
        let script=startup_preferences(root.path());assert!(script.contains("\"theme\":\"dark\""));assert!(!script.contains("<script>"));assert!(!script.contains("secret"));
    }
    #[test] fn auto_preference_survives_native_storage_and_first_frame() {
        let root=tempfile::tempdir().unwrap();fs::create_dir_all(root.path().join("data")).unwrap();
        assert!(startup_preferences(root.path()).contains("\"extractionMethod\":\"auto\""));
        for choice in ["pure","smart","auto"] {
            let saved=local_settings(root.path(),json!({"extractionMethod":choice})).unwrap();
            assert_eq!(saved["extractionMethod"],choice);
            assert!(startup_preferences(root.path()).contains(&format!("\"extractionMethod\":\"{choice}\"")));
        }
        assert!(local_settings(root.path(),json!({"extractionMethod":"unknown"})).is_err());
    }
    #[test] fn legacy_text_settings_retire_models_and_keep_unrelated_preferences() {
        let root=tempfile::tempdir().unwrap();fs::create_dir_all(root.path().join("data")).unwrap();
        let path=root.path().join("data/settings.json");
        let prior=json!({"textPack":"old-pack","textDevice":"gpu","textVision":true,"textBodyGenerator":"reviewed","theme":"neon","clueEnabled":true});
        fs::write(&path,serde_json::to_vec(&prior).unwrap()).unwrap();
        let saved=local_settings(root.path(),json!({})).unwrap();
        assert_eq!(saved["theme"],"neon");assert_eq!(saved["clueEnabled"],true);assert_eq!(saved["textHandShapes"],false);
        for key in ["textPack","textDevice","textVision","textBodyGenerator"]{assert!(saved.get(key).is_none());}
        assert_eq!(local_settings(root.path(),json!({"textHandShapes":false})).unwrap()["textHandShapes"],false);
        assert_eq!(local_settings(root.path(),json!({"textHandShapes":true})).unwrap()["textHandShapes"],true);
        assert_eq!(local_settings(root.path(),json!({"motion":"reduced"})).unwrap()["textHandShapes"],true);
        assert!(local_settings(root.path(),json!({"textHandShapes":"yes"})).is_err());
    }
    #[test] fn clue_choice_survives_native_storage_first_frame_and_unrelated_changes() {
        let root=tempfile::tempdir().unwrap();fs::create_dir_all(root.path().join("data")).unwrap();
        let path=root.path().join("data/settings.json");
        assert_eq!(local_settings(root.path(),json!({})).unwrap()["clueEnabled"],false);
        for enabled in [false,true] {
            let saved=local_settings(root.path(),json!({"clueEnabled":enabled,"theme":"neon"})).unwrap();
            assert_eq!(saved["clueEnabled"],enabled);
            assert!(startup_preferences(root.path()).contains(&format!("\"clueEnabled\":{enabled}")));
            assert_eq!(local_settings(root.path(),json!({"motion":"reduced"})).unwrap()["clueEnabled"],enabled);
        }
        let before=fs::read(&path).unwrap();
        assert!(local_settings(root.path(),json!({"clueEnabled":"off"})).is_err());
        assert_eq!(fs::read(path).unwrap(),before);
    }
    #[test] fn cropped_joint_choice_defaults_on_and_survives_native_startup() {
        let root=tempfile::tempdir().unwrap();fs::create_dir_all(root.path().join("data")).unwrap();
        assert_eq!(local_settings(root.path(),json!({})).unwrap()["zeroCroppedJoints"],true);
        for enabled in [false,true] {
            assert_eq!(local_settings(root.path(),json!({"zeroCroppedJoints":enabled})).unwrap()["zeroCroppedJoints"],enabled);
            assert!(startup_preferences(root.path()).contains(&format!("\"zeroCroppedJoints\":{enabled}")));
            assert_eq!(local_settings(root.path(),json!({"theme":"light"})).unwrap()["zeroCroppedJoints"],enabled);
        }
        assert!(local_settings(root.path(),json!({"zeroCroppedJoints":"on"})).is_err());
    }
    /// Explicit opt-in: checks the developer's existing files, not disposable fixtures.
    #[test]
    #[ignore]
    fn workspace_components_and_private_gpu_worker() {
        let root=PathBuf::from(std::env::var_os("POSESNAP_TEST_ROOT").expect("Use check-native.ps1 -ValidateWorkspace"));
        let engine=Engine::new(root.clone()).unwrap();
        let started=std::time::Instant::now();
        let last=Mutex::new((String::new(),std::time::Instant::now()));
        let snapshot=engine.verify(false,&|s|{
            let mut last=last.lock().unwrap();
            if last.0!=s.message || last.1.elapsed()>=std::time::Duration::from_secs(3){
                if let Some(v)=s.verification {eprintln!("{:.1}s · {} · {}/{} components · {}/{} files · {:.1}/{:.1} MiB read",started.elapsed().as_secs_f64(),s.message,v.completed,v.total,v.files_examined,v.files_total,v.bytes_read as f64/1048576.,v.bytes_total as f64/1048576.);}
                last.0=s.message;last.1=std::time::Instant::now();
            }
        }).unwrap();
        let first_seconds=started.elapsed().as_secs_f64();
        let failures:Vec<_>=snapshot.components.iter().filter(|c|c.required&&c.state!="installed").map(|c|format!("{}: {}",c.label,c.message)).collect();
        assert!(failures.is_empty(),"{}",failures.join("\n"));
        // Repeat the exact browser-only then full-check sequence used at launch.
        let repeated=std::time::Instant::now();let second=Engine::new(root.clone()).unwrap();assert!(second.verify_browser().unwrap());
        let rehashed=Mutex::new(Vec::new());second.verify(false,&|s|{if s.verification.as_ref().is_some_and(|v|v.stage.as_deref()==Some("hashing")){rehashed.lock().unwrap().push(s.message);}}).unwrap();
        let cached_rehashes=rehashed.lock().unwrap().clone();
        assert!(cached_rehashes.is_empty(),"Unchanged launch rehashed components: {:?}",cached_rehashes);
        let cached_seconds=repeated.elapsed().as_secs_f64();
        let worker=Worker{root:root.clone(),child:Mutex::new(None),transport:Mutex::new(None),active:Mutex::new(None),session:Mutex::new(())};
        let health_started=std::time::Instant::now();
        let health=worker.exchange(json!({"jobId":"engine-integration","method":"health","payload":{}}),&|_|{}).unwrap();
        worker.stop();
        engine.health(Ok(health["gpu"].as_str().unwrap().into()),&|_|{});
        assert!(engine.snapshot().ready);
        let evidence=json!({"verified":true,"components":snapshot.components.iter().map(|c|json!({"id":c.id,"state":c.state})).collect::<Vec<_>>(),"firstSeconds":first_seconds,"cachedLaunchSeconds":cached_seconds,"cachedRehashedComponents":cached_rehashes,"healthSeconds":health_started.elapsed().as_secs_f64(),"gpu":health["gpu"]});
        fs::write(root.join("temp/native-tests/startup-validation.json"),serde_json::to_vec_pretty(&evidence).unwrap()).unwrap();
        eprintln!("Private engine verified on {} · first {:.2}s · cached launch {:.2}s",health["gpu"],first_seconds,cached_seconds);
    }
    #[test]
    #[ignore]
    fn upstream_public_download_metadata() {
        // HEAD validates HTTPS/redirects and advertised sizes without downloading weights.
        let root=tempfile::tempdir().unwrap(); let engine=Engine::new(root.path().into()).unwrap();
        let client=download::client(false).unwrap();
        for c in &engine.catalogue.components {
            for artifact in &c.artifacts {
                for url in &artifact.urls {
                    let response=client.head(url).send().unwrap_or_else(|e|panic!("{} source: {e}",c.label));
                    assert!(response.status().is_success(),"{}: HTTP {}",c.label,response.status());
                    if let Some(size)=response.headers().get(reqwest::header::CONTENT_LENGTH).and_then(|v|v.to_str().ok()).and_then(|v|v.parse::<u64>().ok()) { assert_eq!(size,artifact.size,"{} upstream size changed",c.label); }
                    eprintln!("{}: HTTPS source reachable",c.label);
                }
            }
        }
    }
}
fn prepare(root:&Path) -> Result<(),String> {
    if root.to_string_lossy().starts_with("\\\\") {return Err("Move PoseSnap to a writable local NTFS folder or an external NTFS drive. Network shares are not supported.".into());}
    #[cfg(windows)] {
        #[link(name="kernel32")] extern "system" {
            fn GetVolumePathNameW(path:*const u16,volume:*mut u16,length:u32)->i32;
            fn GetVolumeInformationW(root:*const u16,name:*mut u16,name_length:u32,serial:*mut u32,max_component:*mut u32,flags:*mut u32,filesystem:*mut u16,filesystem_length:u32)->i32;
        }
        let path:Vec<u16>=root.to_string_lossy().encode_utf16().chain(Some(0)).collect();let mut volume=[0u16;1024];let mut filesystem=[0u16;32];
        if unsafe{GetVolumePathNameW(path.as_ptr(),volume.as_mut_ptr(),volume.len() as u32)}==0||unsafe{GetVolumeInformationW(volume.as_ptr(),std::ptr::null_mut(),0,std::ptr::null_mut(),std::ptr::null_mut(),std::ptr::null_mut(),filesystem.as_mut_ptr(),filesystem.len() as u32)}==0 {return Err("PoseSnap could not check its drive. Use a writable local NTFS folder.".into());}
        let length=filesystem.iter().position(|c|*c==0).unwrap_or(filesystem.len());
        if String::from_utf16_lossy(&filesystem[..length])!="NTFS"{return Err("PoseSnap requires a writable NTFS folder. Move it to a local NTFS drive or an external NTFS drive.".into());}
    }
    for dir in ["data","data/history","data/rigs","data/cache","data/webview","temp","temp/jobs","logs"] { fs::create_dir_all(root.join(dir)).map_err(|_|"PoseSnap needs a writable local folder. Move the complete folder somewhere you can write, then launch again.".to_string())?; }
    let probe=root.join("data/.write-test");fs::write(&probe,b"portable").map_err(|_|"Move PoseSnap to a writable folder. It will not store data in AppData.".to_string())?;let _=fs::remove_file(probe);
    Ok(())
}
fn main() {
    let root = match portable_root() {
        Ok(root) => root,
        Err(error) => {
            startup_error(&error);
            return;
        }
    };
    if let Err(message)=prepare(&root) { startup_error(&message);return; }
    if std::env::set_current_dir(&root).is_err(){startup_error("PoseSnap could not open its own folder. Move the complete app to a writable local folder and try again.");return;}
    // Scope temporary storage to this app and its browser children. This does
    // not change Windows' or other applications' environment configuration.
    std::env::set_var("TEMP",root.join("temp"));
    std::env::set_var("TMP",root.join("temp"));
    let engine=match Engine::new(root.clone()){Ok(e)=>Arc::new(e),Err(message)=>{startup_error(&message);return;}};
    let runtime=root.join("runtime/webview2");
    let browser_ready=match engine.verify_browser(){Ok(ready)=>ready,Err(message)=>{startup_error(&message);return;}};
    #[cfg(windows)] if !browser_ready||std::env::args().any(|s|s=="--engine-setup") {
        match bootstrap::run(engine.clone()){Ok(true)=>(),Ok(false)=>return,Err(message)=>{startup_error(&message);return;}}
        if !runtime.join("msedgewebview2.exe").is_file(){return;}
    }
    if !runtime.join("msedgewebview2.exe").is_file(){startup_error("Import the private browser in PoseSnap's engine setup window.");return;}
    std::env::set_var("WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",&runtime);
    std::env::set_var("WEBVIEW2_USER_DATA_FOLDER",root.join("data/webview"));
    std::env::set_var("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS","--disable-background-networking --disable-component-update --disable-sync --no-first-run");
    if let Err(message)=prepare_webview_permissions(&root,&runtime){startup_error(&message);return;}
    let worker=Arc::new(Worker{root:root.clone(),child:Mutex::new(None),transport:Mutex::new(None),active:Mutex::new(None),session:Mutex::new(())});
    let face_root=root.clone();
    let app = tauri::Builder::default().manage(worker).manage(engine).manage(Arc::new(engagement::Service::new(root.join("data")))).plugin(tauri_plugin_dialog::init())
        .register_uri_scheme_protocol("expression",move|_,request|{
            let result = face_assets::asset(&face_root, request.uri().path(), request.method());
            match result{
                Ok((bytes,mime))=>tauri::http::Response::builder().status(200).header("Content-Type",mime).header("Access-Control-Allow-Origin","*").header("Cache-Control","no-store").body(bytes).unwrap(),
                Err(message)=>tauri::http::Response::builder().status(404).header("Access-Control-Allow-Origin","*").body(message.into_bytes()).unwrap()
            }
        })
        .invoke_handler(tauri::generate_handler![request,cancel,clipboard_image,engine_status,engine_task,engine_pause,open_external_url,support_event])
        .setup(move |app| {
            let window = (|| -> tauri::Result<()> {
                let (available_width, available_height) = app.primary_monitor()?.map(|monitor| {
                    let area = monitor.work_area();
                    let scale = monitor.scale_factor();
                    (f64::from(area.size.width) / scale, f64::from(area.size.height) / scale)
                }).unwrap_or((1600., 1000.));
                let fit = (available_width * 0.94 / 1440.)
                    .min((available_height - 48.) * 0.94 / 810.)
                    .min(1.);
                tauri::WebviewWindowBuilder::new(app, "main", tauri::WebviewUrl::default())
                    .title("PoseSnap")
                    .initialization_script(startup_preferences(&root))
                    .inner_size(1440. * fit, 810. * fit)
                    .min_inner_size(
                        960_f64.min(available_width * 0.94),
                        540_f64.min((available_height - 48.) * 0.94),
                    )
                    .center()
                    .data_directory(root.join("data/webview"))
                    .build()?;
                Ok(())
            })();
            if let Err(error) = window {
                // Tauri panics when an error escapes its setup callback.
                startup_error(&format!("PoseSnap could not open its workspace: {error}"));
                app.handle().exit(1);
            }
            Ok(())
        })
        .build(tauri::generate_context!());
    let app = match app {
        Ok(app) => app,
        Err(error) => {
            startup_error(&format!("PoseSnap could not start its desktop runtime: {error}"));
            return;
        }
    };
    app.run(|handle,event|{if matches!(event,tauri::RunEvent::Exit){handle.state::<Arc<Worker>>().stop();}});
}
fn prepare_webview_permissions(root:&Path,runtime:&Path)->Result<(),String>{
    #[cfg(windows)] {
        #[repr(C)] struct Version {size:u32,major:u32,minor:u32,build:u32,platform:u32,service:[u16;128]}
        #[link(name="ntdll")] extern "system" {fn RtlGetVersion(version:*mut Version)->i32;}
        let mut version=Version{size:std::mem::size_of::<Version>() as u32,major:0,minor:0,build:0,platform:0,service:[0;128]};
        let marker=root.join("data/webview-permissions.json");
        if unsafe{RtlGetVersion(&mut version)}==0&&version.major==10&&version.build<22000 {
            let current=runtime.to_string_lossy().to_string();
            if fs::read_to_string(&marker).ok().as_deref()!=Some(&current){
                let mut command=Command::new(std::env::var("SystemRoot").unwrap_or("C:\\Windows".into())+"\\System32\\icacls.exe");
                let result=command.arg(runtime).args(["/grant","*S-1-15-2-1:(OI)(CI)(RX)","*S-1-15-2-2:(OI)(CI)(RX)"]).creation_flags(0x08000000).output().map_err(|e|e.to_string())?;
                if !result.status.success(){return Err("Windows 10 could not grant WebView2 read access to its private runtime folder. Move PoseSnap to a folder you own and try again.".into());}
                fs::write(marker,current).map_err(|e|e.to_string())?;
            }
        }
    }
    Ok(())
}
fn startup_error(message:&str) {
    #[cfg(windows)] {
        #[link(name="user32")] extern "system" {fn MessageBoxW(h:usize,text:*const u16,caption:*const u16,flags:u32)->i32;}
        let text:Vec<u16>=message.encode_utf16().chain(Some(0)).collect();let caption:Vec<u16>="PoseSnap — portable folder".encode_utf16().chain(Some(0)).collect();unsafe{MessageBoxW(0,text.as_ptr(),caption.as_ptr(),0x10);}
    }
    #[cfg(not(windows))] eprintln!("{message}");
}
