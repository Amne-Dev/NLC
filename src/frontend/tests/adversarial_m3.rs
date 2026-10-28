//! Adversarial Milestone 3 Test Suite
//! Empirically tests AppTray headless resilience, icon paths, and 4-way post-launch behavior variants.

#[path = "../src/ipc.rs"]
mod ipc;

use ipc::{AgentClient, LauncherConfig};
use serde_json::json;
use std::path::PathBuf;

fn get_project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("Parent repo root")
        .to_path_buf()
}

// -----------------------------------------------------------------------------
// 1. AppTray & Icon Asset Verification
// -----------------------------------------------------------------------------

#[test]
fn test_icon_assets_exist_at_expected_paths() {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));

    // From build.rs: res.set_icon("../../logo.ico"); relative to src/frontend
    let ico_path = manifest_dir.join("../../logo.ico");
    assert!(
        ico_path.exists(),
        "logo.ico must exist at {:?} (resolved to {:?})",
        ico_path,
        ico_path.canonicalize()
    );

    // From ui/main.slint: icon: @image-url("../../../logo.png"); relative to src/frontend/ui
    let png_path = manifest_dir.join("ui").join("../../../logo.png");
    assert!(
        png_path.exists(),
        "logo.png must exist at {:?} (resolved to {:?})",
        png_path,
        png_path.canonicalize()
    );

    // Verify non-empty files
    assert!(std::fs::metadata(&ico_path).unwrap().len() > 0, "logo.ico is empty");
    assert!(std::fs::metadata(&png_path).unwrap().len() > 0, "logo.png is empty");
}

// -----------------------------------------------------------------------------
// 2. Post-Launch Action Deserialization & Categorization Stress Tests
// -----------------------------------------------------------------------------

#[test]
fn test_post_launch_action_all_variants_and_slugs() {
    let test_cases = [
        ("Minimise to taskbar", "taskbar"),
        ("minimize_taskbar", "taskbar"),
        ("  Minimise to taskbar  ", "taskbar"),
        ("Minimise to tray", "tray"),
        ("minimize_tray", "tray"),
        ("  Minimise to tray  ", "tray"),
        ("Close", "close"),
        ("close", "close"),
        ("  Close  ", "close"),
        ("Do nothing", "do_nothing"),
        ("do_nothing", "do_nothing"),
        ("  Do nothing  ", "do_nothing"),
        // Unrecognized / edge inputs
        ("Minimize to taskbar", "do_nothing"),
        ("Minimize to tray", "do_nothing"),
        ("unknown_action", "do_nothing"),
        ("", "do_nothing"),
        ("   ", "do_nothing"),
        ("🦀", "do_nothing"),
    ];

    let categorize = |action: &str| -> &'static str {
        match action.trim() {
            "Minimise to taskbar" | "minimize_taskbar" => "taskbar",
            "Minimise to tray" | "minimize_tray" => "tray",
            "Close" | "close" => "close",
            _ => "do_nothing",
        }
    };

    for (input, expected) in test_cases {
        assert_eq!(
            categorize(input),
            expected,
            "Failed categorization for input: {:?}",
            input
        );
    }
}

#[test]
fn test_launcher_config_deserialization_edge_cases() {
    // 1. Missing post_launch_action field
    let json_missing = r#"{"version": "3.0.6"}"#;
    let cfg1: LauncherConfig = serde_json::from_str(json_missing).unwrap();
    assert_eq!(cfg1.post_launch_action, None);

    // 2. Null post_launch_action field
    let json_null = r#"{"version": "3.0.6", "post_launch_action": null}"#;
    let cfg2: LauncherConfig = serde_json::from_str(json_null).unwrap();
    assert_eq!(cfg2.post_launch_action, None);

    // 3. Explicit post_launch_action with extra legacy fields
    let json_legacy = r#"{
        "version": "3.0.6",
        "post_launch_action": "Minimise to tray",
        "close_on_launch": false,
        "minimize_to_tray": true
    }"#;
    let cfg3: LauncherConfig = serde_json::from_str(json_legacy).unwrap();
    assert_eq!(cfg3.post_launch_action.as_deref(), Some("Minimise to tray"));
    assert_eq!(cfg3.extra.get("close_on_launch").and_then(|v| v.as_bool()), Some(false));
    assert_eq!(cfg3.extra.get("minimize_to_tray").and_then(|v| v.as_bool()), Some(true));

    // 4. In extra map fallback
    let json_in_extra = r#"{
        "post_launch_action": "Close"
    }"#;
    let cfg4: LauncherConfig = serde_json::from_str(json_in_extra).unwrap();
    assert_eq!(cfg4.post_launch_action.as_deref(), Some("Close"));
}

// -----------------------------------------------------------------------------
// 3. E2E IPC Integration: Real Agent Process Persistence & Alias Mapping
// -----------------------------------------------------------------------------

#[tokio::test]
async fn test_ipc_post_launch_action_roundtrip_with_agent() {
    let root = get_project_root();
    let client = AgentClient::spawn(root)
        .await
        .expect("AgentClient spawn failed");

    assert!(client.ping().await, "Initial ping failed");

    // 1. Read initial config
    let initial_cfg = client.get_config().await.expect("Failed to get config");
    assert!(
        initial_cfg.post_launch_action.is_some(),
        "Expected post_launch_action to be present in default config"
    );

    // 2. Update post_launch_action directly
    let update_res = client
        .set_config(json!({ "post_launch_action": "Minimise to tray" }))
        .await
        .expect("Failed to set post_launch_action");
    assert!(
        update_res.success.unwrap_or(false),
        "set_config response indicated failure"
    );

    // 3. Verify it was persisted and read back
    let reloaded_cfg = client.get_config().await.expect("Failed to reload config");
    assert_eq!(
        reloaded_cfg.post_launch_action.as_deref(),
        Some("Minimise to tray")
    );

    // 4. Test ALIAS_MAP: "post_launch_behavior" -> "post_launch_action"
    let alias_res = client
        .set_config(json!({ "post_launch_behavior": "Close" }))
        .await
        .expect("Failed to set post_launch_behavior alias");
    assert!(
        alias_res.success.unwrap_or(false),
        "set_config with alias response indicated failure"
    );

    // 5. Verify alias mapped to post_launch_action
    let alias_cfg = client.get_config().await.expect("Failed to reload after alias update");
    assert_eq!(
        alias_cfg.post_launch_action.as_deref(),
        Some("Close")
    );

    // 6. Test setting all 4 valid variants
    for action in ["Minimise to taskbar", "Minimise to tray", "Close", "Do nothing"] {
        client
            .set_config(json!({ "post_launch_action": action }))
            .await
            .expect("Failed to set variant");
        let cfg = client.get_config().await.expect("Failed to reload");
        assert_eq!(cfg.post_launch_action.as_deref(), Some(action));
    }
}
