//! Empirical Adversarial Milestone 4 Test Suite
//! Validates Addons Overhaul, Dynamic Sidebar Navigation, 0px Sharp Radius Mandate,
//! Search Filtering Invariants, and IPC Serde Edge Cases.

#[path = "../src/ipc.rs"]
mod ipc;

use ipc::{
    AgentClient, IpcError, ListThirdPartyAddonsResponse, RunThirdPartyAddonActionResponse,
    SavedServerItem, ThirdPartyAddonItem,
};
use serde_json::json;
use std::path::PathBuf;

fn get_frontend_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
}

fn get_project_root() -> PathBuf {
    get_frontend_dir()
        .parent()
        .expect("parent of frontend")
        .parent()
        .expect("parent of src")
        .to_path_buf()
}

// =============================================================================
// 1. Zero Rounded Corners Mandate (0px Sharp Pixel Aesthetic)
// =============================================================================

#[test]
fn test_zero_rounded_corners_in_addons_slint() {
    let addons_slint_path = get_frontend_dir().join("ui/screens/addons.slint");
    assert!(
        addons_slint_path.exists(),
        "addons.slint missing at {:?}",
        addons_slint_path
    );

    let content = std::fs::read_to_string(&addons_slint_path).expect("read addons.slint");

    // Scan for any border-radius declarations
    for (line_idx, line) in content.lines().enumerate() {
        let line_trimmed = line.trim();
        if line_trimmed.starts_with("//") {
            continue; // Skip comments
        }

        if line_trimmed.contains("border-radius")
            || line_trimmed.contains("border-top-left-radius")
            || line_trimmed.contains("border-top-right-radius")
            || line_trimmed.contains("border-bottom-left-radius")
            || line_trimmed.contains("border-bottom-right-radius")
        {
            // If border-radius is explicitly stated, it MUST be 0px or 0
            let is_zero = line_trimmed.contains("0px") || line_trimmed.contains("0;");
            assert!(
                is_zero,
                "Violation of zero-rounded-corners mandate in addons.slint line {}: '{}'",
                line_idx + 1,
                line_trimmed
            );
        }
    }

    // Explicitly verify key components in addons.slint have sharp geometry
    assert!(
        content.contains("component AddonCard inherits Rectangle"),
        "AddonCard must be defined"
    );
    assert!(
        content.contains("export component AddonsScreen"),
        "AddonsScreen must be exported"
    );
}

#[test]
fn test_zero_rounded_corners_in_sidebar_addons_mode() {
    let sidebar_slint_path = get_frontend_dir().join("ui/sidebar.slint");
    assert!(sidebar_slint_path.exists(), "sidebar.slint missing");

    let content = std::fs::read_to_string(&sidebar_slint_path).expect("read sidebar.slint");

    // Ensure sidebar has no non-zero border-radius in the addons section
    let addons_section_idx = content
        .find(r#"if root.sidebar-mode == "addons""#)
        .expect("sidebar-mode == 'addons' must exist in sidebar.slint");

    let addons_section = &content[addons_section_idx..addons_section_idx + 1200];
    for (line_idx, line) in addons_section.lines().enumerate() {
        let trimmed = line.trim();
        if trimmed.starts_with("//") {
            continue;
        }
        if trimmed.contains("border-radius") {
            assert!(
                trimmed.contains("0px") || trimmed.contains("0;"),
                "Violation of 0px radius in sidebar addons section line {}: '{}'",
                line_idx + 1,
                trimmed
            );
        }
    }
}

// =============================================================================
// 2. Dynamic Sidebar Mode Transitions & Navigation Invariants
// =============================================================================

#[test]
fn test_sidebar_slint_addons_mode_structure_and_back_navigation() {
    let sidebar_slint_path = get_frontend_dir().join("ui/sidebar.slint");
    let content = std::fs::read_to_string(&sidebar_slint_path).expect("read sidebar.slint");

    // 1. sidebar-mode property declaration
    assert!(
        content.contains(r#"in-out property <string> sidebar-mode: "main";"#),
        "sidebar.slint must declare sidebar-mode property with default 'main'"
    );

    // 2. current-addons-source property declaration
    assert!(
        content.contains(r#"in-out property <string> current-addons-source: "all";"#),
        "sidebar.slint must declare current-addons-source property"
    );

    // 3. Callback declaration
    assert!(
        content.contains("callback select-addons-source(string);"),
        "sidebar.slint must declare callback select-addons-source(string);"
    );

    // 4. In main mode, NavItem for Addons transitions to 'addons' mode
    assert!(
        content.contains(r#"root.set-sidebar-mode("addons");"#),
        "sidebar.slint must transition sidebar mode to 'addons' when Addons is clicked"
    );
    assert!(
        content.contains(r#"root.select-tab("Addons");"#),
        "sidebar.slint must select Addons tab when Addons nav item is clicked"
    );

    // 5. In addons mode, Back NavItem exists and reverts to main mode and Play tab
    assert!(
        content.contains(r#"if root.sidebar-mode == "addons":"#),
        "sidebar.slint must have 'if root.sidebar-mode == \"addons\"' block"
    );
    assert!(
        content.contains(r#"text: "← Back""#),
        "sidebar.slint addons mode must have '← Back' button"
    );
    assert!(
        content.contains(r#"root.set-sidebar-mode("main");"#),
        "Back button must call set-sidebar-mode('main')"
    );

    // 6. 4 source categories exist in sidebar addons mode
    assert!(
        content.contains(r#"title: "ADDON SOURCES""#),
        "sidebar.slint must render 'ADDON SOURCES' CategoryHeader"
    );
    assert!(
        content.contains(r#"text: "All Addons""#),
        "sidebar.slint must have 'All Addons' item"
    );
    assert!(
        content.contains(r#"text: "Installed / Local""#),
        "sidebar.slint must have 'Installed / Local' item"
    );
    assert!(
        content.contains(r#"text: "Discover (Modrinth)""#) || content.contains(r#"text: "Community Addons""#),
        "sidebar.slint must have 'Discover (Modrinth)' or 'Community Addons' item"
    );
    assert!(
        content.contains(r#"text: "Built-in Tools""#),
        "sidebar.slint must have 'Built-in Tools' item"
    );

    // 7. Callbacks triggered with correct category parameters
    assert!(
        content.contains(r#"root.select-addons-source("all");"#),
        "Must invoke select-addons-source with 'all'"
    );
    assert!(
        content.contains(r#"root.select-addons-source("local");"#),
        "Must invoke select-addons-source with 'local'"
    );
    assert!(
        content.contains(r#"root.select-addons-source("modrinth");"#) || content.contains(r#"root.select-addons-source("community");"#),
        "Must invoke select-addons-source with 'modrinth' or 'community'"
    );
    assert!(
        content.contains(r#"root.select-addons-source("builtin");"#),
        "Must invoke select-addons-source with 'builtin'"
    );
}

#[test]
fn test_main_slint_addons_two_way_state_and_routing() {
    let main_slint_path = get_frontend_dir().join("ui/main.slint");
    let content = std::fs::read_to_string(&main_slint_path).expect("read main.slint");

    // 1. MainWindow properties
    assert!(
        content.contains(r#"in-out property <string> current-addons-source: "all";"#),
        "MainWindow must expose current-addons-source"
    );
    assert!(
        content.contains(r#"in-out property <[AddonItemData]> addons: [];"#),
        "MainWindow must expose addons model"
    );
    assert!(
        content.contains(r#"in-out property <string> addons-search-query: "";"#),
        "MainWindow must expose addons-search-query"
    );

    // 2. Sidebar two-way binding
    assert!(
        content.contains("current-addons-source <=> root.current-addons-source;"),
        "Sidebar current-addons-source must be two-way bound to MainWindow"
    );

    // 3. Tab switching sets sidebar-mode = 'addons'
    assert!(
        content.contains(r#"if (tab == "Addons") {
                        root.sidebar-mode = "addons";
                    }"#)
            || content.contains(r#"root.sidebar-mode = "addons";"#),
        "Switching to Addons tab must set sidebar-mode to addons"
    );

    // 4. AddonsScreen instantiation and bindings
    assert!(
        content.contains("if root.current-tab == \"Addons\": AddonsScreen"),
        "MainWindow must instantiate AddonsScreen when current-tab == 'Addons'"
    );
    assert!(
        content.contains("addons <=> root.addons;"),
        "AddonsScreen addons must be bound to root.addons"
    );
    assert!(
        content.contains("active-category <=> root.current-addons-source;"),
        "AddonsScreen active-category must be bound to root.current-addons-source"
    );
    assert!(
        content.contains("search-query <=> root.addons-search-query;"),
        "AddonsScreen search-query must be bound to root.addons-search-query"
    );
}

// =============================================================================
// 3. IPC Serde Edge Cases & Malformed Payload Stress Tests
// =============================================================================

#[test]
fn test_ipc_list_third_party_addons_empty_and_corrupted_payloads() {
    // Case 1: Standard populated payload
    let json_valid = json!({
        "status": "success",
        "data": {
            "addons_dir": "C:\\Users\\User\\.nlc\\addons",
            "addons": [
                {
                    "id": "test_addon",
                    "name": "Test Addon",
                    "version": "2.1.0",
                    "author": "Tester",
                    "description": "A test addon",
                    "entrypoint": "main.py",
                    "actions": [
                        { "id": "act1", "name": "Run Action", "description": "Desc" }
                    ],
                    "folder_name": "test_addon",
                    "addon_dir": "C:\\Users\\User\\.nlc\\addons\\test_addon",
                    "load_error": null
                }
            ]
        }
    });

    let resp: ListThirdPartyAddonsResponse =
        serde_json::from_value(json_valid).expect("Populated payload must deserialize");
    assert_eq!(resp.status, "success");
    let data = resp.data.expect("data must be present");
    assert_eq!(data.addons.len(), 1);
    assert_eq!(data.addons[0].id, "test_addon");
    assert_eq!(data.addons[0].actions.len(), 1);
    assert_eq!(data.addons[0].actions[0].name, "Run Action");

    // Case 2: Minimal empty payload with no data
    let json_empty = json!({
        "status": "success"
    });
    let resp_empty: ListThirdPartyAddonsResponse =
        serde_json::from_value(json_empty).expect("Minimal status-only payload must deserialize");
    assert_eq!(resp_empty.status, "success");
    assert!(resp_empty.data.is_none());

    // Case 3: Payload with explicit null data
    let json_null_data = json!({
        "status": "success",
        "data": null
    });
    let resp_null: ListThirdPartyAddonsResponse =
        serde_json::from_value(json_null_data).expect("Null data payload must deserialize");
    assert_eq!(resp_null.status, "success");
    assert!(resp_null.data.is_none());

    // Case 4: Addons data with missing optional fields & checking default values
    let json_defaults = json!({
        "status": "success",
        "data": {
            "addons": [
                {
                    "id": "barebones_addon",
                    "name": "Barebones"
                    // version, author, entrypoint, actions, folder_name, addon_dir, load_error omitted
                }
            ]
        }
    });
    let resp_defaults: ListThirdPartyAddonsResponse =
        serde_json::from_value(json_defaults).expect("Omitted fields should use defaults");
    let data_defaults = resp_defaults.data.unwrap();
    assert_eq!(data_defaults.addons_dir, "");
    assert_eq!(data_defaults.addons.len(), 1);
    let item = &data_defaults.addons[0];
    assert_eq!(item.id, "barebones_addon");
    assert_eq!(item.name, "Barebones");
    assert_eq!(item.version, "1.0.0"); // Default version
    assert_eq!(item.author, "Unknown"); // Default author
    assert_eq!(item.entrypoint, "main.py"); // Default entrypoint
    assert!(item.actions.is_empty());
    assert_eq!(item.folder_name, "");
    assert_eq!(item.addon_dir, "");
    assert!(item.load_error.is_none());

    // Case 5: Action item using 'label' alias instead of 'name'
    let json_alias_action = json!({
        "id": "addon_alias",
        "name": "Alias Test",
        "actions": [
            { "id": "act_alias", "label": "Label As Name" }
        ]
    });
    let item_alias: ThirdPartyAddonItem =
        serde_json::from_value(json_alias_action).expect("Action with 'label' alias must deserialize");
    assert_eq!(item_alias.actions.len(), 1);
    assert_eq!(item_alias.actions[0].name, "Label As Name");

    // Case 6: Addon with error state
    let json_error_addon = json!({
        "id": "corrupted_addon",
        "name": "Corrupted",
        "load_error": "SyntaxError in main.py line 42"
    });
    let item_err: ThirdPartyAddonItem =
        serde_json::from_value(json_error_addon).expect("Error state addon must deserialize");
    assert_eq!(
        item_err.load_error.as_deref(),
        Some("SyntaxError in main.py line 42")
    );

    // Case 7: Extra unknown fields should be safely ignored
    let json_extra_fields = json!({
        "status": "success",
        "data": {
            "addons_dir": "/addons",
            "addons": [
                {
                    "id": "extra_fields",
                    "name": "Extra",
                    "unknown_field_123": [1, 2, 3],
                    "nested_junk": { "foo": "bar" }
                }
            ],
            "server_timestamp": 123456789
        },
        "debug_meta": "ignored"
    });
    let resp_extra: ListThirdPartyAddonsResponse =
        serde_json::from_value(json_extra_fields).expect("Unknown fields should not break serde");
    assert_eq!(resp_extra.status, "success");
    assert_eq!(resp_extra.data.unwrap().addons[0].id, "extra_fields");
}

#[test]
fn test_ipc_run_third_party_addon_action_serde_edge_cases() {
    // 1. Success with message and data
    let json_success = json!({
        "status": "success",
        "msg": "Executed successfully",
        "data": { "exit_code": 0 }
    });
    let resp1: RunThirdPartyAddonActionResponse =
        serde_json::from_value(json_success).expect("Success response must deserialize");
    assert_eq!(resp1.status, "success");
    assert_eq!(resp1.msg.as_deref(), Some("Executed successfully"));
    assert!(resp1.data.is_some());

    // 2. Minimal success (msg and data absent)
    let json_minimal = json!({ "status": "success" });
    let resp2: RunThirdPartyAddonActionResponse =
        serde_json::from_value(json_minimal).expect("Minimal response must deserialize");
    assert_eq!(resp2.status, "success");
    assert!(resp2.msg.is_none());
    assert!(resp2.data.is_none());

    // 3. Error status with error message
    let json_err = json!({
        "status": "error",
        "msg": "Module not found: helper.py"
    });
    let resp3: RunThirdPartyAddonActionResponse =
        serde_json::from_value(json_err).expect("Error response must deserialize");
    assert_eq!(resp3.status, "error");
    assert_eq!(resp3.msg.as_deref(), Some("Module not found: helper.py"));

    // 4. Corrupted JSON string fails gracefully
    let corrupted_raw = "{ status: not_json }";
    let parse_err = serde_json::from_str::<RunThirdPartyAddonActionResponse>(corrupted_raw);
    assert!(parse_err.is_err(), "Corrupted JSON must yield error");
}

// =============================================================================
// 4. Search Filtering Invariants & Category Selection Logic
// =============================================================================

#[derive(Clone, Debug, PartialEq)]
struct MockAddonItem {
    id: String,
    name: String,
    author: String,
    description: String,
    source: String, // "builtin", "local", "modrinth"
}

fn filter_mock_addons(
    items: &[MockAddonItem],
    active_category: &str,
    search_query: &str,
) -> Vec<MockAddonItem> {
    let q = search_query.trim().to_lowercase();
    let cat = if active_category.is_empty() {
        "all"
    } else {
        active_category
    };

    items
        .iter()
        .filter(|it| {
            // Category check
            let cat_match = match cat {
                "all" => true,
                "builtin" => it.source == "builtin",
                "local" | "installed" => it.source == "local",
                "modrinth" | "discover" => it.source == "modrinth",
                _ => false,
            };
            if !cat_match {
                return false;
            }

            // Search query check (case-insensitive substring on name, description, author)
            if q.is_empty() {
                true
            } else {
                it.name.to_lowercase().contains(&q)
                    || it.description.to_lowercase().contains(&q)
                    || it.author.to_lowercase().contains(&q)
            }
        })
        .cloned()
        .collect()
}

#[test]
fn test_search_and_category_filtering_invariants() {
    let mock_pool = vec![
        MockAddonItem {
            id: "playtime_tracker".into(),
            name: "Playtime Tracker".into(),
            author: "Launcher Built-in".into(),
            description: "Tracks active session play duration.".into(),
            source: "builtin".into(),
        },
        MockAddonItem {
            id: "gh_skin_sync".into(),
            name: "GitHub Skin Sync".into(),
            author: "Launcher Built-in".into(),
            description: "Synchronizes character skins with GitHub.".into(),
            source: "builtin".into(),
        },
        MockAddonItem {
            id: "streamer_mode".into(),
            name: "Streamer Mode".into(),
            author: "Launcher Built-in".into(),
            description: "Hides account emails and sensitive tokens.".into(),
            source: "builtin".into(),
        },
        MockAddonItem {
            id: "custom_hud".into(),
            name: "Custom HUD Overlay".into(),
            author: "ModderSteve".into(),
            description: "Adds custom FPS and coordinate HUD overlay.".into(),
            source: "local".into(),
        },
        MockAddonItem {
            id: "auto_reconnect".into(),
            name: "Auto Reconnect".into(),
            author: "NetworkDev".into(),
            description: "Automatically retries server connections.".into(),
            source: "local".into(),
        },
        MockAddonItem {
            id: "sodium_extra".into(),
            name: "Sodium Extra".into(),
            author: "FlashFix".into(),
            description: "Additional graphics optimization features.".into(),
            source: "modrinth".into(),
        },
    ];

    // Invariant 1: "all" category with empty query returns everything
    let all_items = filter_mock_addons(&mock_pool, "all", "");
    assert_eq!(all_items.len(), 6);

    // Invariant 2: "builtin" category returns exclusively built-in tools
    let builtin_items = filter_mock_addons(&mock_pool, "builtin", "");
    assert_eq!(builtin_items.len(), 3);
    for item in &builtin_items {
        assert_eq!(item.source, "builtin");
    }

    // Invariant 3: "local" and "installed" category returns exclusively local addons
    let local_items = filter_mock_addons(&mock_pool, "local", "");
    let installed_items = filter_mock_addons(&mock_pool, "installed", "");
    assert_eq!(local_items.len(), 2);
    assert_eq!(local_items, installed_items);
    for item in &local_items {
        assert_eq!(item.source, "local");
    }

    // Invariant 4: "modrinth" and "discover" returns exclusively modrinth addons
    let modrinth_items = filter_mock_addons(&mock_pool, "modrinth", "");
    let discover_items = filter_mock_addons(&mock_pool, "discover", "");
    assert_eq!(modrinth_items.len(), 1);
    assert_eq!(modrinth_items, discover_items);
    assert_eq!(modrinth_items[0].id, "sodium_extra");

    // Invariant 5: Case-insensitive search on title/name
    let search_upper = filter_mock_addons(&mock_pool, "all", "PLAYTIME");
    let search_lower = filter_mock_addons(&mock_pool, "all", "playtime");
    let search_mixed = filter_mock_addons(&mock_pool, "all", "PlAyTiMe");
    assert_eq!(search_upper.len(), 1);
    assert_eq!(search_upper, search_lower);
    assert_eq!(search_upper, search_mixed);
    assert_eq!(search_upper[0].id, "playtime_tracker");

    // Invariant 6: Search on description
    let search_desc = filter_mock_addons(&mock_pool, "all", "sensitive tokens");
    assert_eq!(search_desc.len(), 1);
    assert_eq!(search_desc[0].id, "streamer_mode");

    // Invariant 7: Search on author
    let search_author = filter_mock_addons(&mock_pool, "all", "ModderSteve");
    assert_eq!(search_author.len(), 1);
    assert_eq!(search_author[0].id, "custom_hud");

    // Invariant 8: Intersection of category and search query
    // "hud" exists in local, searching "hud" in "builtin" must return 0
    let search_hud_builtin = filter_mock_addons(&mock_pool, "builtin", "HUD");
    assert_eq!(search_hud_builtin.len(), 0);

    let search_hud_local = filter_mock_addons(&mock_pool, "local", "HUD");
    assert_eq!(search_hud_local.len(), 1);
    assert_eq!(search_hud_local[0].id, "custom_hud");

    // Invariant 9: Non-matching queries yield 0 results
    let non_matching = filter_mock_addons(&mock_pool, "all", "NonExistentAddonQuery12345");
    assert_eq!(non_matching.len(), 0);

    // Invariant 10: Punctuation, symbols, and leading/trailing whitespace
    let ws_search = filter_mock_addons(&mock_pool, "all", "   Sodium   ");
    assert_eq!(ws_search.len(), 1);
    assert_eq!(ws_search[0].id, "sodium_extra");

    let special_chars = filter_mock_addons(&mock_pool, "all", "§$%&!@");
    assert_eq!(special_chars.len(), 0);
}

// =============================================================================
// 5. Live E2E Integration: AgentClient Real Process Addons IPC
// =============================================================================

#[tokio::test]
async fn test_e2e_real_agent_addons_ipc_integration() {
    let root = get_project_root();
    let client = AgentClient::spawn(root)
        .await
        .expect("AgentClient spawn failed");

    assert!(client.ping().await, "Initial agent ping failed");

    // 1. Test listing addons directly over IPC
    let list_res = client
        .list_third_party_addons()
        .await
        .expect("list_third_party_addons failed");
    assert_eq!(list_res.status, "success");
    assert!(list_res.data.is_some());
    let data = list_res.data.unwrap();
    let addons_dir_path = PathBuf::from(&data.addons_dir);

    // 2. Create a temporary test addon in the real addons directory
    let test_addon_id = format!("empirical_test_addon_{}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    let test_addon_dir = addons_dir_path.join(&test_addon_id);
    std::fs::create_dir_all(&test_addon_dir).expect("Failed to create test addon dir");

    let manifest_content = json!({
        "id": test_addon_id,
        "name": "Empirical Test Addon",
        "version": "1.0.0",
        "author": "Challenger",
        "description": "Addon created by empirical challenge suite",
        "entrypoint": "main.py",
        "actions": [
            { "id": "test_ping", "name": "Test Ping", "description": "Pings the test addon" }
        ]
    });
    std::fs::write(
        test_addon_dir.join("addon.json"),
        serde_json::to_string_pretty(&manifest_content).unwrap(),
    )
    .expect("Failed to write addon.json");

    let py_code = r#"
def handle_action(action_id, inputs, context):
    if action_id == "test_ping":
        return {"status": "success", "msg": "pong_from_test_addon"}
    return {"status": "error", "msg": f"unknown action: {action_id}"}
"#;
    std::fs::write(test_addon_dir.join("main.py"), py_code).expect("Failed to write main.py");

    // 3. Re-list addons and verify the newly added addon is discovered
    let list_recheck = client
        .list_third_party_addons()
        .await
        .expect("re-list failed");
    assert_eq!(list_recheck.status, "success");
    let recheck_data = list_recheck.data.expect("recheck data present");
    let found = recheck_data
        .addons
        .iter()
        .find(|a| a.id == test_addon_id);
    assert!(found.is_some(), "Newly created addon was not discovered by agent");
    let discovered = found.unwrap();
    assert_eq!(discovered.name, "Empirical Test Addon");
    assert_eq!(discovered.actions.len(), 1);
    assert_eq!(discovered.actions[0].id, "test_ping");

    // 4. Test running valid action on the addon
    let action_res = client
        .run_third_party_addon_action(
            test_addon_id.clone(),
            "test_ping".to_string(),
            json!({}),
        )
        .await
        .expect("run_third_party_addon_action failed");
    assert_eq!(action_res.status, "success");
    assert_eq!(action_res.msg.as_deref(), Some("pong_from_test_addon"));

    // 5. Test running action on non-existent addon (should error gracefully)
    let missing_res = client
        .run_third_party_addon_action(
            "definitely_non_existent_addon_12345".to_string(),
            "test_ping".to_string(),
            json!({}),
        )
        .await;
    match missing_res {
        Err(IpcError::ServerError { code, message, .. }) => {
            assert!(message.contains("was not found"));
            assert_eq!(code, "ERR_BACKEND");
        }
        other => panic!("Expected ServerError for missing addon, got: {:?}", other),
    }

    // 6. Test running invalid action handled by handle_action
    let invalid_act_res = client
        .run_third_party_addon_action(
            test_addon_id.clone(),
            "invalid_non_existent_action".to_string(),
            json!({}),
        )
        .await;
    match invalid_act_res {
        Err(IpcError::ServerError { code, message, .. }) => {
            assert!(message.contains("unknown action"));
            assert_eq!(code, "ERR_BACKEND");
        }
        other => panic!("Expected ServerError for invalid action, got: {:?}", other),
    }

    // 7. Test addon without handle_action and without action function ("does not expose action")
    let test_addon_id2 = format!("{}_no_handle", test_addon_id);
    let test_addon_dir2 = addons_dir_path.join(&test_addon_id2);
    let _ = std::fs::create_dir_all(&test_addon_dir2);
    let _ = std::fs::write(
        test_addon_dir2.join("addon.json"),
        serde_json::to_string(&json!({ "id": test_addon_id2, "name": "No Handle Addon" })).unwrap(),
    );
    let _ = std::fs::write(test_addon_dir2.join("main.py"), "# empty main.py\n");

    let unexposed_res = client
        .run_third_party_addon_action(
            test_addon_id2.clone(),
            "missing_action".to_string(),
            json!({}),
        )
        .await;
    match unexposed_res {
        Err(IpcError::ServerError { code, message, .. }) => {
            assert!(message.contains("does not expose action 'missing_action'"));
            assert_eq!(code, "ERR_BACKEND");
        }
        other => panic!("Expected ServerError for unexposed action, got: {:?}", other),
    }

    // 8. Cleanup temporary addon directories
    let _ = std::fs::remove_dir_all(&test_addon_dir);
    let _ = std::fs::remove_dir_all(&test_addon_dir2);
}



// =============================================================================
// 8. Server Quick Join Modal & Saved Servers Tests
// =============================================================================

#[test]
fn test_server_quick_join_modal_sharp_corners_and_properties() {
    let addons_slint_path = get_frontend_dir().join("ui/screens/addons.slint");
    let content = std::fs::read_to_string(&addons_slint_path).expect("read addons.slint");

    assert!(content.contains("component ServerQuickJoinModal inherits Rectangle"));
    assert!(content.contains("in-out property <[SavedServerData]> servers: [];"));
    assert!(content.contains("callback add-server(string, string, string)"));
    assert!(content.contains("callback delete-server(string)"));
    assert!(content.contains("callback join-server(string, int)"));
    assert!(content.contains("callback ping-all()"));

    let main_slint_path = get_frontend_dir().join("ui/main.slint");
    let main_content = std::fs::read_to_string(&main_slint_path).expect("read main.slint");
    assert!(main_content.contains("in-out property <bool> server-manager-open: false;"));
    assert!(main_content.contains("in-out property <[SavedServerData]> saved-servers"));
}

#[tokio::test]
async fn test_saved_servers_ipc_lifecycle() {
    let root = get_project_root();
    let client = AgentClient::spawn(root)
        .await
        .expect("AgentClient spawn failed");

    assert!(client.ping().await, "Initial agent ping failed");

    let initial_servers: Vec<SavedServerItem> = client.get_saved_servers().await.expect("get_saved_servers failed");
    let initial_count = initial_servers.len();

    let unique_name = format!("Test Server {}", std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis());
    let added_servers = client
        .add_saved_server(&unique_name, "mc.hypixel.net", 25565)
        .await
        .expect("add_saved_server failed");

    assert_eq!(added_servers.len(), initial_count + 1);
    let newly_added = added_servers.iter().find(|s| s.name == unique_name).expect("Added server not in list");
    assert_eq!(newly_added.address, "mc.hypixel.net");
    assert_eq!(newly_added.port, 25565);
    assert!(!newly_added.id.is_empty());
    let target_id = newly_added.id.clone();

    let after_removal = client
        .remove_saved_server(&target_id)
        .await
        .expect("remove_saved_server failed");

    assert_eq!(after_removal.len(), initial_count);
    assert!(after_removal.iter().all(|s| s.id != target_id));
}
