/// Cross-platform native file and directory selection dialogs via `rfd`.

fn configure_filters(mut dialog: rfd::FileDialog, filter: &str) -> rfd::FileDialog {
    if filter.is_empty() {
        return dialog;
    }

    let parts: Vec<&str> = filter.split('|').collect();
    for chunk in parts.chunks(2) {
        let (label, patterns_str) = if chunk.len() == 2 {
            (chunk[0].trim(), chunk[1].trim())
        } else {
            ("Files", chunk[0].trim())
        };

        // Parse pattern strings like "*.png;*.jpg" or "javaw.exe;java.exe" or "*"
        let mut extensions: Vec<String> = Vec::new();
        let mut allow_all = false;

        for pat in patterns_str.split(';') {
            let p = pat.trim();
            if p == "*" || p == "*.*" {
                allow_all = true;
                break;
            }
            // Strip wildcard prefixes like "*." or "*.*"
            let ext = if let Some(stripped) = p.strip_prefix("*.") {
                stripped
            } else if let Some(stripped) = p.strip_prefix('.') {
                stripped
            } else {
                p
            };
            if !ext.is_empty() {
                extensions.push(ext.to_string());
            }
        }

        if !allow_all && !extensions.is_empty() {
            let ext_refs: Vec<&str> = extensions.iter().map(|s| s.as_str()).collect();
            dialog = dialog.add_filter(label, &ext_refs);
        }
    }

    dialog
}

/// Displays a native file picker dialog and returns the selected path, or `None` if canceled.
pub fn prompt_open_file(filter: &str) -> Option<String> {
    let dialog = configure_filters(rfd::FileDialog::new(), filter);
    dialog.pick_file().map(|path| path.to_string_lossy().to_string())
}

/// Displays a native file save dialog with a suggested file name and returns the selected path, or `None` if canceled.
pub fn prompt_save_file(default_name: &str, filter: &str) -> Option<String> {
    let mut dialog = configure_filters(rfd::FileDialog::new(), filter);
    if !default_name.is_empty() {
        dialog = dialog.set_file_name(default_name);
    }
    dialog.save_file().map(|path| path.to_string_lossy().to_string())
}

/// Displays a native directory picker dialog and returns the selected path, or `None` if canceled.
pub fn prompt_open_folder() -> Option<String> {
    rfd::FileDialog::new()
        .pick_folder()
        .map(|path| path.to_string_lossy().to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_dialog_functions_exist() {
        // Simple compilation & signature check without opening GUI in headless test environment
        let _f: fn(&str) -> Option<String> = prompt_open_file;
        let _s: fn(&str, &str) -> Option<String> = prompt_save_file;
        let _d: fn() -> Option<String> = prompt_open_folder;
    }
}
