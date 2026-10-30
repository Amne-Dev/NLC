fn main() {
    slint_build::compile("ui/main.slint").expect("Failed to compile Slint UI definitions");

    let manifest_dir = std::path::PathBuf::from(
        std::env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR not set"),
    );
    let out_dir = std::path::PathBuf::from(
        std::env::var_os("OUT_DIR").expect("OUT_DIR not set"),
    );
    let tray_in = manifest_dir.join("ui/tray.slint");
    let tray_out = out_dir.join("tray.rs");
    let tray_config = slint_build::CompilerConfiguration::new();
    let deps = slint_build::compile_with_output_path(&tray_in, &tray_out, tray_config)
        .expect("Failed to compile Slint tray definitions");
    for dep in deps {
        println!("cargo:rerun-if-changed={}", dep.display());
    }

    #[cfg(windows)]
    {
        let mut res = winres::WindowsResource::new();
        res.set_icon("../../logo.ico");
        res.set("ProductName", "Ny-Luna");
        res.set("FileDescription", "Ny-Luna");
        res.set("OriginalFilename", "NyLuna.exe");
        res.set("LegalCopyright", "Amne-Dev");
        let _ = res.compile();
    }
}
