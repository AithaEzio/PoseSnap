//! Native first-run recovery: deliberately independent of WebView2 and Python.
use crate::engine::Engine;
use std::{ptr::{null, null_mut}, sync::{Arc, Mutex, OnceLock}};
use windows_sys::Win32::{Foundation::*, Graphics::Gdi::*, System::LibraryLoader::GetModuleHandleW,
    UI::{Input::KeyboardAndMouse::EnableWindow, WindowsAndMessaging::*}};

struct State { engine: Arc<Engine>, closing: bool, continued: bool, rendered: String }
static STATE: OnceLock<Mutex<Option<State>>> = OnceLock::new();
fn wide(value: &str) -> Vec<u16> { value.encode_utf16().chain(Some(0)).collect() }

unsafe fn child(parent: HWND, class: &str, title: &str, style: u32, x: i32, y: i32, width: i32, height: i32, id: usize) -> HWND {
    let window = CreateWindowExW(0, wide(class).as_ptr(), wide(title).as_ptr(), WS_CHILD | WS_VISIBLE | style,
                                 x, y, width, height, parent, id as HMENU, GetModuleHandleW(null()), null());
    SendMessageW(window, WM_SETFONT, GetStockObject(DEFAULT_GUI_FONT) as usize, 1);
    window
}
unsafe fn text(window: HWND) -> String {
    let mut buffer = vec![0; GetWindowTextLengthW(window) as usize + 1];
    let count = GetWindowTextW(window, buffer.as_mut_ptr(), buffer.len() as i32);
    String::from_utf16_lossy(&buffer[..count as usize])
}
unsafe extern "system" fn procedure(window: HWND, message: u32, wparam: WPARAM, lparam: LPARAM) -> LRESULT {
    match message {
        WM_COMMAND => {
            let id = wparam & 0xffff;
            let mut state = STATE.get().unwrap().lock().unwrap(); let state = state.as_mut().unwrap();
            let snapshot = state.engine.snapshot();
            if id == 15 { state.engine.pause(); return 0; }
            if id == 14 && !snapshot.active && snapshot.components.iter().any(|c| c.id == "browser" && c.state == "installed") {
                state.continued = true; DestroyWindow(window); return 0;
            }
            if [11,12,13].contains(&id) && !snapshot.active {
                let selected = SendMessageW(GetDlgItem(window, 10), CB_GETCURSEL, 0, 0).max(0) as usize;
                let Some(component) = state.engine.catalogue.components.get(selected) else { return 0; };
                let component = component.id.clone(); let engine = state.engine.clone();
                let source = text(GetDlgItem(window, 16)).trim().trim_matches('"').to_owned();
                std::thread::spawn(move || {
                    let result = if id == 13 { engine.verify(true, &|_| {}) }
                                 else if id == 12 && source.trim().is_empty() { Err("Paste the component folder or exact archive path, then choose Import.".into()) }
                                 else { engine.install(&component, (id == 12).then(|| std::path::Path::new(source.trim())), false, &|_| {}) };
                    if let Err(error) = result { engine.health(Err(error), &|_| {}); }
                });
            }
            0
        }
        WM_TIMER => {
            let mut state = STATE.get().unwrap().lock().unwrap(); let state = state.as_mut().unwrap();
            let snapshot = state.engine.snapshot();
            let mut message = format!("{}\r\n\r\n", snapshot.message);
            for c in &snapshot.components {
                let status=match c.state.as_str(){"installed"=>"Installed","missing"=>"Missing","unchecked"=>"Not checked","checking"=>"Checking",_=>"Needs attention"};
                message += &format!("{}: {}\r\n  {}\r\n", c.label, status, c.locations.join("; "));
            }
            for t in &snapshot.transfers { message += &format!("\r\n{}: {:.1} / {:.1} MB", t.label, t.bytes as f64 / 1e6, t.total as f64 / 1e6); }
            let selected = SendMessageW(GetDlgItem(window, 10), CB_GETCURSEL, 0, 0).max(0) as usize;
            if let Some(c) = snapshot.components.get(selected) { if !c.message.is_empty() { message += &format!("\r\n\r\n{}", c.message); } EnableWindow(GetDlgItem(window,11), (!snapshot.active && c.downloadable) as i32); }
            if message != state.rendered { SetWindowTextW(GetDlgItem(window,17), wide(&message).as_ptr()); state.rendered = message; }
            for id in [10,12,13,16] { EnableWindow(GetDlgItem(window,id), (!snapshot.active) as i32); }
            EnableWindow(GetDlgItem(window,15), snapshot.active as i32);
            EnableWindow(GetDlgItem(window,14), (!snapshot.active && snapshot.components.iter().any(|c| c.id == "browser" && c.state == "installed")) as i32);
            if state.closing && !snapshot.active { DestroyWindow(window); }
            0
        }
        WM_CLOSE => {
            let mut state = STATE.get().unwrap().lock().unwrap(); let state = state.as_mut().unwrap();
            if state.engine.snapshot().active { state.closing = true; state.engine.pause(); } else { DestroyWindow(window); }
            0
        }
        WM_DESTROY => { PostQuitMessage(0); 0 }
        _ => DefWindowProcW(window,message,wparam,lparam),
    }
}

pub fn run(engine: Arc<Engine>) -> Result<bool, String> {
    *STATE.get_or_init(|| Mutex::new(None)).lock().map_err(|_|"Setup state failed")? = Some(State { engine: engine.clone(), closing: false, continued: false, rendered: String::new() });
    unsafe {
        let instance = GetModuleHandleW(null()); let class = wide("PoseSnapEngineSetup");
        let registration = WNDCLASSW { lpfnWndProc: Some(procedure), hInstance: instance, lpszClassName: class.as_ptr(), hCursor: LoadCursorW(null_mut(), IDC_ARROW), hbrBackground: (COLOR_WINDOW + 1) as HBRUSH, ..std::mem::zeroed() };
        RegisterClassW(&registration);
        let window = CreateWindowExW(0, class.as_ptr(), wide("PoseSnap · Portable engine setup").as_ptr(), WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                                     CW_USEDEFAULT, CW_USEDEFAULT, 780, 650, null_mut(), null_mut(), instance, null());
        if window.is_null() { return Err("Could not open the portable setup window".into()); }
        child(window,"STATIC","Prepare your local PoseSnap engine",0,24,20,720,26,1);
        child(window,"STATIC","Components stay in this folder. No system Python, browser installer or administrator access is used.",0,24,52,720,40,2);
        let combo = child(window,"COMBOBOX","", CBS_DROPDOWNLIST as u32 | WS_VSCROLL,24,96,710,280,10);
        for c in &engine.catalogue.components { SendMessageW(combo,CB_ADDSTRING,0,wide(&c.label).as_ptr() as isize); }
        SendMessageW(combo,CB_SETCURSEL,0,0);
        child(window,"STATIC","Offline fallback: paste a component folder, complete PoseSnap folder or verified archive path.",0,24,137,710,38,3);
        child(window,"EDIT","",WS_BORDER | ES_AUTOHSCROLL as u32,24,178,710,28,16);
        child(window,"BUTTON","Download / resume",0,24,220,170,32,11);
        child(window,"BUTTON","Import from disk",0,206,220,155,32,12);
        child(window,"BUTTON","Verify files",0,373,220,130,32,13);
        child(window,"BUTTON","Pause",0,515,220,98,32,15);
        child(window,"EDIT","Checking private components…",WS_BORDER | WS_VSCROLL | ES_MULTILINE as u32 | ES_READONLY as u32 | ES_AUTOVSCROLL as u32,24,270,710,275,17);
        child(window,"BUTTON","Open workspace",BS_DEFPUSHBUTTON as u32,564,563,170,32,14);
        child(window,"STATIC","Missing browser? Import it here first. Remaining components can be managed in Settings.",0,24,565,520,38,4);
        SetTimer(window,1,150,None); ShowWindow(window,SW_SHOW); UpdateWindow(window);
        std::thread::spawn(move || { if let Err(e) = engine.verify_browser() { engine.health(Err(e),&|_| {}); } });
        let mut message: MSG = std::mem::zeroed();
        while GetMessageW(&mut message,null_mut(),0,0)>0 { if IsDialogMessageW(window,&message)==0 { TranslateMessage(&message); DispatchMessageW(&message); } }
    }
    let state = STATE.get().unwrap().lock().map_err(|_|"Setup state failed")?.take().ok_or("Setup state missing")?;
    Ok(state.continued)
}
