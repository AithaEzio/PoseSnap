fn main() {
    tauri_build::build();
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        // Retain Tauri's manifest and icon; replace its default product-name-only description.
        let resource = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("resource.rc");
        let source = std::fs::read_to_string(&resource).expect("Generated Windows resources");
        let description = "PoseSnap — Convert photos into Genesis 8 and 9 poses locally for DAZ Studio.";
        let revised = source.lines().map(|line| {
            if line.trim_start().starts_with("VALUE \"FileDescription\",") {
                format!("VALUE \"FileDescription\", \"{}\"", description)
            } else { line.to_owned() }
        }).collect::<Vec<_>>().join("\n");
        std::fs::write(&resource, revised).expect("PoseSnap Windows metadata");
        // Tauri already emitted the linker directive. Recompile that same resource once
        // without emitting a second directive, which would duplicate VERSIONINFO.
        let compiled = std::process::Command::new("rc.exe")
            .arg("/nologo").arg("/fo").arg(resource.with_extension("lib"))
            .arg(&resource).status().expect("Windows SDK resource compiler");
        assert!(compiled.success(), "PoseSnap Windows resource compilation failed");
    }
}
