/// Cross-platform native file and directory selection dialogs via `rfd`.

/// Displays a native file picker dialog and returns the selected path, or `None` if canceled.
///
/// Supports filter strings formatted like standard Windows dialog filters:
/// `"Label (*.ext)|*.ext"` or `"Label (*.a;*.b)|*.a;*.b|All files (*.*)|*.*"`
pub fn prompt_open_file(filter: &str) -> Option<String> {
    let mut dialog = rfd::FileDialog::new();

    if !filter.is_empty() {
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

            if allow_all {
                // Many platforms allow all files if no extension filter is specified or via wildcard
                // In rfd, adding filter with empty or wildcard is not strictly needed, but we can register standard extensions
            } else if !extensions.is_empty() {
                let ext_refs: Vec<&str> = extensions.iter().map(|s| s.as_str()).collect();
                dialog = dialog.add_filter(label, &ext_refs);
            }
        }
    }

    dialog.pick_file().map(|path| path.to_string_lossy().to_string())
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
        let _d: fn() -> Option<String> = prompt_open_folder;
    }
}
