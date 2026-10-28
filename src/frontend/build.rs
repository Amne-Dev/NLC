fn main() {
    slint_build::compile("ui/main.slint").expect("Failed to compile Slint UI definitions");

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

