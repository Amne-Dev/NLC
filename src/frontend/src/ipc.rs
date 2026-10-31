#![allow(dead_code)]

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::fmt;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, Command};
use tokio::sync::{broadcast, mpsc, oneshot, Mutex};
use tokio::time::{timeout, Duration};
use uuid::Uuid;

// -----------------------------------------------------------------------------
// Error Hierarchy
// -----------------------------------------------------------------------------

#[derive(Debug)]
pub enum IpcError {
    Io(std::io::Error),
    Serialization(serde_json::Error),
    ChannelSendError(String),
    RequestCanceled,
    AgentDisconnected(String),
    ServerError {
        code: String,
        message: String,
        details: Option<Value>,
    },
    Timeout(String),
}

impl fmt::Display for IpcError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => write!(f, "I/O error: {}", e),
            Self::Serialization(e) => write!(f, "JSON serialization error: {}", e),
            Self::ChannelSendError(e) => write!(f, "Channel send error: {}", e),
            Self::RequestCanceled => write!(f, "Request canceled (response channel dropped)"),
            Self::AgentDisconnected(msg) => write!(f, "Agent disconnected: {}", msg),
            Self::ServerError { code, message, .. } => write!(f, "Server error [{}]: {}", code, message),
            Self::Timeout(msg) => write!(f, "Timeout: {}", msg),
        }
    }
}

impl std::error::Error for IpcError {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        match self {
            Self::Io(e) => Some(e),
            Self::Serialization(e) => Some(e),
            _ => None,
        }
    }
}

impl From<std::io::Error> for IpcError {
    fn from(err: std::io::Error) -> Self {
        Self::Io(err)
    }
}

impl From<serde_json::Error> for IpcError {
    fn from(err: serde_json::Error) -> Self {
        Self::Serialization(err)
    }
}

// -----------------------------------------------------------------------------
// Wire Message Protocols
// -----------------------------------------------------------------------------

#[derive(Debug, Deserialize)]
struct RpcWireMessage {
    id: Option<String>,
    #[allow(dead_code)]
    action: Option<String>,
    result: Option<Value>,
    error: Option<Value>,
    event: Option<String>,
    payload: Option<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RpcEvent {
    pub event: String,
    pub payload: Value,
}

// -----------------------------------------------------------------------------
// Strongly-Typed Domain Models
// -----------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LaunchGameRequest {
    #[serde(default)]
    pub version: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub instance_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub installation_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub loader: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub custom_java: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub ram_mb: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub mock: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub force_update: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub server: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub port: Option<u16>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LaunchGameResponse {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub launch_id: Option<String>,
    #[serde(default)]
    pub pid: Option<u32>,
    #[serde(default)]
    pub message: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct KillGameRequest {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub launch_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LauncherConfig {
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub first_run_completed: Option<bool>,
    #[serde(default)]
    pub modpack_tutorial_completed: Option<bool>,
    #[serde(default)]
    pub ram: Option<u32>,
    #[serde(default)]
    pub theme_id: Option<String>,
    #[serde(default)]
    pub custom_accent: Option<String>,
    #[serde(default)]
    pub animations_enabled: Option<bool>,
    #[serde(default)]
    pub enable_walking_mobs: Option<bool>,
    #[serde(default)]
    pub streamer_mode: Option<bool>,
    #[serde(default)]
    pub rpc_enabled: Option<bool>,
    #[serde(default)]
    pub rpc_detail_mode: Option<String>,
    #[serde(default)]
    pub rpc_show_timer: Option<bool>,
    #[serde(default)]
    pub rpc_show_idle: Option<bool>,
    #[serde(default)]
    pub rpc_show_server: Option<bool>,
    #[serde(default)]
    pub post_launch_action: Option<String>,
    #[serde(default)]
    pub active_profile_index: Option<usize>,
    #[serde(default)]
    pub active_account: Option<String>,
    #[serde(default)]
    pub installations: Option<Vec<Value>>,
    #[serde(flatten)]
    pub extra: HashMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetConfigRequest {
    pub updates: Value,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SetConfigResponse {
    #[serde(default)]
    pub status: Option<String>,
    #[serde(default)]
    pub success: Option<bool>,
    #[serde(default)]
    pub updated_keys: Option<Vec<String>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountItem {
    #[serde(default)]
    pub id: Option<String>,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub username: Option<String>,
    #[serde(rename = "type", default)]
    pub r#type: Option<String>,
    #[serde(default)]
    pub account_type: Option<String>,
    #[serde(default)]
    pub active: Option<bool>,
    #[serde(default)]
    pub skin_path: Option<String>,
    #[serde(default)]
    pub skin_model: Option<String>,
    #[serde(default)]
    pub uuid: Option<String>,
    #[serde(default)]
    pub index: Option<usize>,
    #[serde(default)]
    pub head_path: Option<String>,
}

impl AccountItem {
    pub fn name(&self) -> &str {
        if let Some(ref n) = self.name {
            let tr = n.trim();
            if !tr.is_empty() { return tr; }
        }
        if let Some(ref u) = self.username {
            let tr = u.trim();
            if !tr.is_empty() { return tr; }
        }
        "Steve"
    }

    pub fn account_type(&self) -> &str {
        if let Some(ref t) = self.r#type {
            let tr = t.trim();
            if !tr.is_empty() { return tr; }
        }
        if let Some(ref a) = self.account_type {
            let tr = a.trim();
            if !tr.is_empty() { return tr; }
        }
        "offline"
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum AccountsListResponse {
    List(Vec<AccountItem>),
    Obj {
        #[serde(default)]
        accounts: Vec<AccountItem>,
        #[serde(default)]
        active_account: Option<String>,
        #[serde(default)]
        active_profile_index: Option<usize>,
    },
    Fallback,
}

impl AccountsListResponse {
    pub fn accounts(&self) -> &[AccountItem] {
        match self {
            Self::List(l) => l.as_slice(),
            Self::Obj { accounts, .. } => accounts.as_slice(),
            Self::Fallback => &[],
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct MicrosoftAuthStartResponse {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub user_code: String,
    #[serde(default)]
    pub verification_uri: String,
    #[serde(default)]
    pub expires_in: u64,
    #[serde(default)]
    pub interval: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SelectAccountRequest {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub index: Option<usize>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ListModsRequest {
    pub instance_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModInfo {
    pub name: String,
    #[serde(alias = "filename", default)]
    pub file: String,
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub first_run_completed: Option<bool>,
    #[serde(default)]
    pub modpack_tutorial_completed: Option<bool>,
    #[serde(default)]
    pub size_bytes: Option<u64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ModListResponse {
    List(Vec<ModInfo>),
    Obj {
        #[serde(default)]
        mods_dir: Option<String>,
        #[serde(default)]
        mods: Vec<ModInfo>,
    },
}

impl ModListResponse {
    pub fn mods(&self) -> &[ModInfo] {
        match self {
            Self::List(l) => l.as_slice(),
            Self::Obj { mods, .. } => mods.as_slice(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModrinthSearchRequest {
    pub query: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub project_type: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub loader: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub version: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub sort: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub limit: Option<u32>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub offset: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModrinthHit {
    #[serde(default)]
    pub project_id: String,
    #[serde(default)]
    pub slug: Option<String>,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub icon_url: Option<String>,
    #[serde(default)]
    pub author: Option<String>,
    #[serde(default)]
    pub project_type: Option<String>,
    #[serde(default)]
    pub categories: Vec<String>,
    #[serde(default)]
    pub downloads: Option<u64>,
    #[serde(default)]
    pub follows: Option<u64>,
    #[serde(default)]
    pub versions: Vec<String>,
    #[serde(default)]
    pub icon_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum ModrinthSearchResponse {
    List(Vec<ModrinthHit>),
    Obj {
        #[serde(default)]
        hits: Vec<ModrinthHit>,
        #[serde(default)]
        total_hits: Option<u64>,
        #[serde(default)]
        offset: Option<u32>,
        #[serde(default)]
        limit: Option<u32>,
    },
}

impl ModrinthSearchResponse {
    pub fn hits(&self) -> &[ModrinthHit] {
        match self {
            Self::List(l) => l.as_slice(),
            Self::Obj { hits, .. } => hits.as_slice(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct GetSkinRequest {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub account_index: Option<usize>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SkinInfoResponse {
    #[serde(default)]
    pub skin_path: Option<String>,
    #[serde(default)]
    pub cape_path: Option<String>,
    #[serde(default)]
    pub skin_model: Option<String>,
    #[serde(default)]
    pub active_cape_id: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SkinRenderFrameRequest {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub skin_path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cape_path: Option<String>,
    #[serde(default)]
    pub yaw_deg: f32,
    #[serde(default)]
    pub pitch_deg: f32,
    #[serde(default)]
    pub walk_phase: f32,
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    #[serde(default)]
    pub model: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SkinRenderFrameResponse {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub image_base64: String,
    #[serde(default)]
    pub width: u32,
    #[serde(default)]
    pub height: u32,
    #[serde(default)]
    pub yaw_deg: f32,
    #[serde(default)]
    pub pitch_deg: f32,
}


#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct InstallationItem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub version: String,
    #[serde(default)]
    pub loader: Option<String>,
    #[serde(default)]
    pub icon: Option<String>,
    #[serde(default)]
    pub r#type: Option<String>,
    #[serde(default)]
    pub last_played: Option<String>,
    #[serde(default)]
    pub created: Option<String>,
    #[serde(default)]
    pub java_executable: Option<String>,
    #[serde(default)]
    pub jvm_arguments: Option<String>,
    #[serde(default)]
    pub resolution_width: Option<i32>,
    #[serde(default)]
    pub resolution_height: Option<i32>,
    #[serde(default)]
    pub game_directory: Option<String>,
    #[serde(default)]
    pub min_ram_mb: Option<u32>,
    #[serde(default)]
    pub max_ram_mb: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModpackItem {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub loader: Option<String>,
    #[serde(default)]
    pub mc_version: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub first_run_completed: Option<bool>,
    #[serde(default)]
    pub modpack_tutorial_completed: Option<bool>,
    #[serde(default)]
    pub pack_release: Option<String>,
    #[serde(default)]
    pub version_name: Option<String>,
    #[serde(default)]
    pub linked_installation_id: Option<String>,
    #[serde(default)]
    pub linked_inst_name: Option<String>,
    #[serde(default)]
    pub is_linked: Option<bool>,
    #[serde(default)]
    pub mod_count: Option<i32>,
    #[serde(default)]
    pub thumbnail: Option<String>,
    #[serde(default)]
    pub icon_letter: Option<String>,
    #[serde(default)]
    pub icon_path: Option<String>,
    #[serde(default)]
    pub has_icon: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModItem {
    #[serde(default)]
    pub id: Option<String>,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub filename: String,
    #[serde(default)]
    pub size_text: Option<String>,
    #[serde(default)]
    pub size: Option<String>,
    #[serde(default)]
    pub size_bytes: Option<u64>,
    #[serde(default)]
    pub enabled: Option<bool>,
    #[serde(default)]
    pub is_active: Option<bool>,
    #[serde(default)]
    pub active: Option<bool>,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub first_run_completed: Option<bool>,
    #[serde(default)]
    pub modpack_tutorial_completed: Option<bool>,
    #[serde(default)]
    pub icon_path: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct VersionManifestResponse {
    pub loader: Option<String>,
    #[serde(default)]
    pub releases: Vec<String>,
    #[serde(default)]
    pub snapshots: Vec<String>,
    pub latest_release: Option<String>,
    pub latest_snapshot: Option<String>,
    #[serde(default)]
    pub versions: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct LoadersResponse {
    #[serde(default)]
    pub loaders: Vec<String>,
    #[serde(default)]
    pub modpack_loaders: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ModpackImportRequest {
    pub archive_path: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub name: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub api_key: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SkinSyncRequest {
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub repo: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub token: Option<String>,
    #[serde(default)]
    pub username: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub skin_path: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub upload: Option<bool>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub download: Option<bool>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SavedServerItem {
    pub id: String,
    pub name: String,
    pub address: String,
    #[serde(default = "default_mc_port")]
    pub port: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ServerPingRequest {
    pub host: String,
    #[serde(default = "default_mc_port")]
    pub port: u16,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub timeout: Option<f64>,
}

fn default_mc_port() -> u16 {
    25565
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ServerPingResponse {
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub online: bool,
    #[serde(default)]
    pub latency_ms: i64,
    #[serde(default)]
    pub version: Option<String>,
    #[serde(default)]
    pub first_run_completed: Option<bool>,
    #[serde(default)]
    pub modpack_tutorial_completed: Option<bool>,
    #[serde(default)]
    pub motd: Option<String>,
    #[serde(default)]
    pub players_online: Option<u32>,
    #[serde(default)]
    pub players_max: Option<u32>,
    #[serde(default)]
    pub favicon: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct PlaytimeStatsResponse {
    #[serde(default)]
    pub total_seconds: u64,
    #[serde(default)]
    pub total_minutes: u64,
    #[serde(default)]
    pub total_launches: u64,
    #[serde(default)]
    pub tracker: HashMap<String, Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScreenshotItem {
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub size: u64,
    #[serde(default)]
    pub modified: f64,
    #[serde(default)]
    pub date: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ScreenshotListResponse {
    #[serde(default)]
    pub dir: String,
    #[serde(default)]
    pub items: Vec<ScreenshotItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct SystemInfoResponse {
    #[serde(default)]
    pub os: String,
    #[serde(default)]
    pub python: String,
    #[serde(default)]
    pub ram: String,
    #[serde(default)]
    pub processor: String,
    #[serde(default)]
    pub javas: Vec<Value>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct DiagnosticsLogsResponse {
    #[serde(default)]
    pub lines: Vec<String>,
    #[serde(default)]
    pub text: String,
}

// -----------------------------------------------------------------------------
// AgentClient Actor Implementation
// -----------------------------------------------------------------------------

#[cfg(windows)]
fn assign_to_kill_on_close_job(child: &Child) {
    type HANDLE = *mut std::ffi::c_void;
    type BOOL = i32;
    type DWORD = u32;

    #[repr(C)]
    struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: DWORD,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: DWORD,
        affinity: usize,
        priority_class: DWORD,
        scheduling_class: DWORD,
    }

    #[repr(C)]
    struct IO_COUNTERS {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
        basic_limit_information: JOBOBJECT_BASIC_LIMIT_INFORMATION,
        io_info: IO_COUNTERS,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_limit: usize,
        peak_job_memory_limit: usize,
    }

    const JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: DWORD = 0x2000;
    const JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: u32 = 9;

    extern "system" {
        fn CreateJobObjectW(lpJobAttributes: *mut std::ffi::c_void, lpName: *const u16) -> HANDLE;
        fn SetInformationJobObject(
            hJob: HANDLE,
            JobObjectInformationClass: u32,
            lpJobObjectInformation: *const std::ffi::c_void,
            cbJobObjectInformationLength: DWORD,
        ) -> BOOL;
        fn AssignProcessToJobObject(hJob: HANDLE, hProcess: HANDLE) -> BOOL;
        fn OpenProcess(dwDesiredAccess: DWORD, bInheritHandle: BOOL, dwProcessId: DWORD) -> HANDLE;
        fn CloseHandle(hObject: HANDLE) -> BOOL;
    }

    if let Some(pid) = child.id() {
        unsafe {
            let job = CreateJobObjectW(std::ptr::null_mut(), std::ptr::null());
            if !job.is_null() {
                let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
                info.basic_limit_information.limit_flags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
                let res = SetInformationJobObject(
                    job,
                    JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                    &info as *const _ as *const std::ffi::c_void,
                    std::mem::size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as DWORD,
                );
                if res != 0 {
                    const PROCESS_SET_QUOTA: DWORD = 0x0100;
                    const PROCESS_TERMINATE: DWORD = 0x0001;
                    let h_proc = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
                    if !h_proc.is_null() {
                        let assigned = AssignProcessToJobObject(job, h_proc);
                        CloseHandle(h_proc);
                        if assigned != 0 {
                            println!("[NLC-Rust] Bound agent.exe (PID {}) to Windows KillOnJobClose Job Object", pid);
                            let _ = job; // Keep handle open for the lifetime of this process
                        } else {
                            CloseHandle(job);
                        }
                    } else {
                        CloseHandle(job);
                    }
                } else {
                    CloseHandle(job);
                }
            }
        }
    }
}

#[derive(Clone)]
pub struct AgentClient {
    req_tx: mpsc::Sender<(String, oneshot::Sender<Result<Value, IpcError>>)>,
    write_tx: mpsc::Sender<String>,
    event_tx: broadcast::Sender<RpcEvent>,
    is_alive: Arc<AtomicBool>,
    child_handle: Arc<Mutex<Option<Child>>>,
}

impl AgentClient {
    pub async fn spawn(project_root: PathBuf) -> Result<Self, IpcError> {
        let exe_dir = std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(|p| p.to_path_buf()))
            .unwrap_or_else(|| project_root.clone());

        let mut agent_candidates = vec![
            exe_dir.join("agent.exe"),
            exe_dir.join("agent"),
            exe_dir.join("bin").join("agent"),
            project_root.join("agent.exe"),
            project_root.join("agent"),
            project_root.join("usr").join("bin").join("agent"),
            project_root.join("bin").join("agent"),
            project_root.join("dist_linux").join("agent"),
        ];

        if let Some(appdir) = std::env::var_os("APPDIR").map(PathBuf::from) {
            agent_candidates.push(appdir.join("usr").join("bin").join("agent"));
            agent_candidates.push(appdir.join("agent"));
        }

        if let Some(parent) = exe_dir.parent() {
            agent_candidates.push(parent.join("agent"));
            agent_candidates.push(parent.join("agent.exe"));
        }

        let found_agent = agent_candidates.into_iter().find(|p| p.is_file());

        let mut child: Child = if let Some(ref agent_bin) = found_agent {
            println!("[NLC-Rust] Spawning packaged agent backend at: {:?}", agent_bin);
            let mut cmd = Command::new(agent_bin);
            cmd.current_dir(&project_root)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            {
                cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
            }
            cmd.spawn()?
        } else {
            let mut resolved_root = project_root.clone();
            if !resolved_root.join("agent.py").exists() && !resolved_root.join("src").join("backend").join("agent.py").exists() {
                if let Some(p) = project_root.parent() {
                    if p.join("agent.py").exists() || p.join("src").join("backend").join("agent.py").exists() {
                        resolved_root = p.to_path_buf();
                    }
                }
            }
            if !resolved_root.join("agent.py").exists() && !resolved_root.join("src").join("backend").join("agent.py").exists() {
                if let Ok(exe) = std::env::current_exe() {
                    for anc in exe.ancestors() {
                        if anc.join("agent.py").exists() || anc.join("src").join("backend").join("agent.py").exists() {
                            resolved_root = anc.to_path_buf();
                            break;
                        }
                    }
                }
            }
            let agent_py = if resolved_root.join("src").join("backend").join("agent.py").exists() {
                resolved_root.join("src").join("backend").join("agent.py")
            } else {
                resolved_root.join("agent.py")
            };
            if !agent_py.is_file() {
                return Err(IpcError::AgentDisconnected(format!(
                    "Agent backend not found. Searched for native binary and python script in {:?}",
                    project_root
                )));
            }
            println!("[NLC-Rust] Launching agent backend at: {:?}", agent_py);
            let python_bin = if cfg!(windows) {
                "python".to_string()
            } else {
                let venv_py = resolved_root.join(".venv").join("bin").join("python");
                if venv_py.is_file() {
                    venv_py.to_string_lossy().to_string()
                } else if std::process::Command::new("python3").arg("--version").output().is_ok() {
                    "python3".to_string()
                } else {
                    "python".to_string()
                }
            };
            let mut cmd = Command::new(&python_bin);
            cmd.current_dir(&resolved_root)
                .arg(&agent_py)
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped());
            #[cfg(windows)]
            {
                cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
            }
            cmd.spawn()?
        };

        if let Some(err_pipe) = child.stderr.take() {
            tokio::spawn(async move {
                use tokio::io::AsyncBufReadExt;
                let mut reader = tokio::io::BufReader::new(err_pipe).lines();
                while let Ok(Some(line)) = reader.next_line().await {
                    eprintln!("[Agent-Log] {}", line);
                }
            });
        }

        let stdin = child.stdin.take().expect("Child stdin unavailable");
        let stdout = child.stdout.take().expect("Child stdout unavailable");

        let pending_requests: Arc<Mutex<HashMap<String, oneshot::Sender<Result<Value, IpcError>>>>> =
            Arc::new(Mutex::new(HashMap::new()));

        let (req_tx, mut req_rx) = mpsc::channel::<(String, oneshot::Sender<Result<Value, IpcError>>)>(256);
        let (write_tx, mut write_rx) = mpsc::channel::<String>(256);
        let (event_tx, _) = broadcast::channel::<RpcEvent>(512);
        let is_alive = Arc::new(AtomicBool::new(true));

        // 1. Line-buffered Stdin Writer Task
        let mut writer = stdin;
        tokio::spawn(async move {
            while let Some(line) = write_rx.recv().await {
                if writer.write_all(line.as_bytes()).await.is_err() {
                    break;
                }
                if writer.write_all(b"\n").await.is_err() {
                    break;
                }
                let _ = writer.flush().await;
            }
        });

        // 2. Pending Request Registration Router Task
        let pending_for_router = pending_requests.clone();
        tokio::spawn(async move {
            while let Some((id, sender)) = req_rx.recv().await {
                pending_for_router.lock().await.insert(id, sender);
            }
        });

        // 3. Stdout Reader & Message Demuxer Task
        let pending_for_reader = pending_requests.clone();
        let event_broadcaster = event_tx.clone();
        let is_alive_reader = is_alive.clone();
        tokio::spawn(async move {
            let mut reader = BufReader::new(stdout).lines();
            loop {
                match reader.next_line().await {
                    Ok(Some(line)) => {
                        let trimmed = line.trim();
                        // Filter non-JSON startup banners or empty lines
                        if trimmed.is_empty() || !trimmed.starts_with('{') {
                            continue;
                        }

                        if let Ok(msg) = serde_json::from_str::<RpcWireMessage>(trimmed) {
                            // Branch A: Correlated RPC Response
                            if let Some(id) = msg.id {
                                if let Some(sender) = pending_for_reader.lock().await.remove(&id) {
                                    if let Some(err_val) = msg.error {
                                        let err_msg = err_val
                                            .get("message")
                                            .and_then(|m| m.as_str())
                                            .or_else(|| err_val.as_str())
                                            .unwrap_or("RPC Error")
                                            .to_string();
                                        let code = err_val
                                            .get("code")
                                            .and_then(|c| c.as_str())
                                            .unwrap_or("ERR_RPC")
                                            .to_string();
                                        let _ = sender.send(Err(IpcError::ServerError {
                                            code,
                                            message: err_msg,
                                            details: None,
                                        }));
                                    } else if let Some(res) = msg.result {
                                        if res.get("status").and_then(|s| s.as_str()) == Some("error") {
                                            let code = res
                                                .get("code")
                                                .and_then(|c| c.as_str())
                                                .unwrap_or("ERR_BACKEND")
                                                .to_string();
                                            let message = res
                                                .get("msg")
                                                .and_then(|m| m.as_str())
                                                .unwrap_or("Backend error")
                                                .to_string();
                                            let details = res.get("details").cloned();
                                            let _ = sender.send(Err(IpcError::ServerError {
                                                code,
                                                message,
                                                details,
                                            }));
                                        } else {
                                            let _ = sender.send(Ok(res));
                                        }
                                    } else {
                                        let _ = sender.send(Ok(Value::Null));
                                    }
                                }
                            }
                            // Branch B: Unsolicited Push Event
                            else if let Some(event_name) = msg.event {
                                let payload = msg.payload.unwrap_or(Value::Null);
                                let _ = event_broadcaster.send(RpcEvent {
                                    event: event_name,
                                    payload,
                                });
                            }
                        }
                    }
                    Ok(None) => {
                        // EOF reached: agent process closed its stdout stream
                        eprintln!("[NLC-Rust] Agent stdout closed (EOF reached)");
                        break;
                    }
                    Err(e) => {
                        eprintln!("[NLC-Rust] Warning reading agent stdout line: {}. Continuing reader loop...", e);
                        continue;
                    }
                }
            }

            // Child process terminated or pipe closed: drain pending requests
            is_alive_reader.store(false, Ordering::SeqCst);
            let mut map = pending_for_reader.lock().await;
            for (id, sender) in map.drain() {
                let _ = sender.send(Err(IpcError::AgentDisconnected(format!(
                    "Agent process exited while request '{}' was pending",
                    id
                ))));
            }

            let _ = event_broadcaster.send(RpcEvent {
                event: "agent_disconnected".to_string(),
                payload: serde_json::json!({
                    "reason": "Process exited or pipe closed"
                }),
            });
        });

        #[cfg(windows)]
        assign_to_kill_on_close_job(&child);

        let child_handle = Arc::new(Mutex::new(Some(child)));

        Ok(AgentClient {
            req_tx,
            write_tx,
            event_tx,
            is_alive,
            child_handle,
        })
    }

    /// Explicitly shuts down the agent backend process
    pub async fn shutdown(&self) {
        println!("[NLC-Rust] Explicitly shutting down agent backend...");
        let _ = tokio::time::timeout(
            Duration::from_millis(400),
            self.call::<Value>("agent_shutdown", serde_json::json!({}))
        ).await;
        let mut guard = self.child_handle.lock().await;
        if let Some(mut child) = guard.take() {
            let _ = child.start_kill();
        }
    }

    /// Subscribe to unsolicited push events
    pub fn subscribe(&self) -> broadcast::Receiver<RpcEvent> {
        self.event_tx.subscribe()
    }

    /// Backwards compatible alias for subscribe
    pub fn subscribe_events(&self) -> broadcast::Receiver<RpcEvent> {
        self.subscribe()
    }

    /// Generic typed remote call with automatic duration scaling for long-running actions
    pub async fn call<T: DeserializeOwned>(&self, action: &str, payload: Value) -> Result<T, IpcError> {
        let timeout_secs = match action {
            "modrinth_install_artifact" | "modpack_import" | "modpack_install_mod" | "system_apply_update" | "launch_game" => 600,
            _ => 15,
        };
        self.call_with_timeout(action, payload, Duration::from_secs(timeout_secs)).await
    }

    /// Generic typed remote call with explicit custom timeout
    pub async fn call_with_timeout<T: DeserializeOwned>(
        &self,
        action: &str,
        payload: Value,
        dur: Duration,
    ) -> Result<T, IpcError> {
        if !self.is_alive.load(Ordering::SeqCst) {
            return Err(IpcError::AgentDisconnected(
                "Agent process is disconnected".to_string(),
            ));
        }

        let req_id = Uuid::new_v4().to_string();
        let wire_req = serde_json::json!({
            "id": req_id,
            "action": action,
            "payload": payload,
        });

        let line = serde_json::to_string(&wire_req)?;
        let (resp_tx, resp_rx) = oneshot::channel();

        self.req_tx
            .send((req_id, resp_tx))
            .await
            .map_err(|e| IpcError::ChannelSendError(e.to_string()))?;

        self.write_tx
            .send(line)
            .await
            .map_err(|e| IpcError::ChannelSendError(e.to_string()))?;

        let resp_result = timeout(dur, resp_rx)
            .await
            .map_err(|_| IpcError::Timeout(format!("IPC request timed out after {}s", dur.as_secs())))?
            .map_err(|_| IpcError::RequestCanceled)??;

        let parsed: T = serde_json::from_value(resp_result)?;
        Ok(parsed)
    }

    // --- Typed Domain RPC Methods ---

    pub async fn get_discord_status(&self) -> Result<Value, IpcError> {
        self.call("get_discord_status", serde_json::json!({})).await
    }

    pub async fn ping(&self) -> bool {
        match self.call::<Value>("ping", Value::Null).await {
            Ok(res) => {
                res.get("status").and_then(|s| s.as_str()) == Some("success")
                    || res.get("data").and_then(|d| d.as_str()) == Some("pong")
            }
            Err(_) => false,
        }
    }

    pub async fn launch_game(&self, req: LaunchGameRequest) -> Result<LaunchGameResponse, IpcError> {
        let payload = serde_json::to_value(req)?;
        self.call("launch_game", payload).await
    }

    pub async fn kill_game(&self, req: KillGameRequest) -> Result<Value, IpcError> {
        let payload = serde_json::to_value(req)?;
        self.call("kill_game", payload).await
    }

    pub async fn cancel_launch(&self) -> Result<Value, IpcError> {
        self.call("cancel_launch", serde_json::json!({})).await
    }

    pub async fn get_config(&self) -> Result<LauncherConfig, IpcError> {
        let res: Value = self.call("config_get", Value::Null).await?;
        let config_val = if let Some(data) = res.get("data") {
            data.clone()
        } else {
            res
        };
        Ok(serde_json::from_value(config_val)?)
    }

    pub async fn set_config(&self, updates: Value) -> Result<SetConfigResponse, IpcError> {
        let payload = serde_json::json!({ "updates": updates });
        self.call("config_set", payload).await
    }

    pub async fn list_accounts(&self) -> Result<AccountsListResponse, IpcError> {
        let res: Value = self.call("accounts_list", Value::Null).await?;
        let data_val = match res.get("data") {
            Some(data) if data.is_object() || data.is_array() => data,
            _ => &res,
        };
        Ok(serde_json::from_value(data_val.clone()).unwrap_or(AccountsListResponse::Fallback))
    }

    pub async fn select_account(&self, req: SelectAccountRequest) -> Result<Value, IpcError> {
        let payload = serde_json::to_value(req)?;
        self.call("accounts_select", payload).await
    }

    pub async fn add_offline_account(&self, username: &str) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "username": username });
        self.call("accounts_auth_offline", payload).await
    }

    pub async fn start_microsoft_auth(&self) -> Result<MicrosoftAuthStartResponse, IpcError> {
        let res: Value = self.call("accounts_auth_microsoft_start", Value::Null).await?;
        Ok(serde_json::from_value(res)?)
    }

    pub async fn auth_elyby(&self, username: &str, password: &str) -> Result<Value, IpcError> {
        let payload = serde_json::json!({
            "username": username,
            "password": password
        });
        self.call("accounts_auth_elyby", payload).await
    }

    pub async fn open_url(&self, url: &str) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "url": url });
        self.call("system_open_url", payload).await
    }

    pub async fn copy_clipboard(&self, text: &str) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "text": text });
        self.call("system_copy_clipboard", payload).await
    }

    pub async fn remove_account_by_target(
        &self,
        index: Option<usize>,
        name: Option<&str>,
        id: Option<&str>,
    ) -> Result<Value, IpcError> {
        let mut map = serde_json::Map::new();
        if let Some(idx) = index {
            map.insert("index".to_string(), serde_json::json!(idx));
        }
        if let Some(n) = name {
            map.insert("name".to_string(), serde_json::json!(n));
            map.insert("username".to_string(), serde_json::json!(n));
        }
        if let Some(i) = id {
            map.insert("id".to_string(), serde_json::json!(i));
        }
        self.call("accounts_remove", serde_json::Value::Object(map)).await
    }

    pub async fn list_mods(&self, instance_id: &str) -> Result<ModListResponse, IpcError> {
        let payload = serde_json::json!({ "instance_id": instance_id });
        let res: Value = self.call("mods_list_installed", payload).await?;
        let data_val = if let Some(data) = res.get("data") {
            data
        } else {
            &res
        };
        Ok(serde_json::from_value(data_val.clone())?)
    }

    pub async fn search_modrinth(&self, req: ModrinthSearchRequest) -> Result<ModrinthSearchResponse, IpcError> {
        let payload = serde_json::to_value(req)?;
        let res: Value = self.call("modrinth_search", payload).await?;
        let data_val = if let Some(data) = res.get("data") {
            data
        } else {
            &res
        };
        if data_val.is_null() {
            return Ok(ModrinthSearchResponse::List(vec![]));
        }
        Ok(serde_json::from_value(data_val.clone())?)
    }

    pub async fn get_skin(&self, req: GetSkinRequest) -> Result<SkinInfoResponse, IpcError> {
        let payload = serde_json::to_value(req)?;
        let res: Value = self.call("skin_get_current", payload).await?;
        let data_val = if let Some(data) = res.get("data") {
            data
        } else {
            &res
        };
        Ok(serde_json::from_value(data_val.clone())?)
    }

    pub async fn render_skin_frame(&self, req: SkinRenderFrameRequest) -> Result<SkinRenderFrameResponse, IpcError> {
        let payload = serde_json::to_value(req)?;
        let res: Value = self.call("skin_render_frame", payload).await?;
        let data_val = if let Some(data) = res.get("data") {
            data
        } else {
            &res
        };
        Ok(serde_json::from_value(data_val.clone())?)
    }


    pub async fn list_instances(&self) -> Result<Vec<InstallationItem>, IpcError> {
        let res: Value = self.call("instances_list", Value::Null).await?;
        let insts_val = if let Some(instances) = res.get("data").and_then(|d| d.get("instances")) {
            instances.clone()
        } else if let Some(instances) = res.get("instances") {
            instances.clone()
        } else if res.is_array() {
            res
        } else {
            Value::Array(Vec::new())
        };
        Ok(serde_json::from_value(insts_val)?)
    }

    pub async fn create_instance(&self, req: Value) -> Result<InstallationItem, IpcError> {
        let res: Value = self.call("instance_create", req).await?;
        let item_val = if let Some(instance) = res.get("instance") {
            instance.clone()
        } else if let Some(data) = res.get("data") {
            data.clone()
        } else {
            res
        };
        Ok(serde_json::from_value(item_val)?)
    }

    pub async fn update_instance(&self, req: Value) -> Result<InstallationItem, IpcError> {
        let res: Value = self.call("instance_update", req).await?;
        let item_val = if let Some(instance) = res.get("instance") {
            instance.clone()
        } else if let Some(data) = res.get("data") {
            data.clone()
        } else {
            res
        };
        Ok(serde_json::from_value(item_val)?)
    }

    pub async fn delete_instance(&self, id: &str) -> Result<bool, IpcError> {
        let payload = serde_json::json!({ "id": id });
        let res: Value = self.call("instance_delete", payload).await?;
        Ok(res.get("success").and_then(|v| v.as_bool()).unwrap_or(true))
    }

    pub async fn duplicate_instance(&self, id: &str) -> Result<String, IpcError> {
        let payload = serde_json::json!({ "id": id });
        let res: Value = self.call("instance_duplicate", payload).await?;
        let new_id = res.get("new_id")
            .and_then(|v| v.as_str())
            .or_else(|| res.get("data").and_then(|d| d.get("id")).and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string();
        Ok(new_id)
    }

    pub async fn list_modpacks(&self) -> Result<Vec<ModpackItem>, IpcError> {
        let res: Value = self.call("modpacks_list", Value::Null).await?;
        let packs_val = if let Some(modpacks) = res.get("data").and_then(|d| d.get("modpacks")) {
            modpacks.clone()
        } else if let Some(modpacks) = res.get("modpacks") {
            modpacks.clone()
        } else if res.is_array() {
            res
        } else {
            Value::Array(Vec::new())
        };
        Ok(serde_json::from_value(packs_val)?)
    }

    pub async fn create_modpack(&self, name: &str, loader: &str, mc_version: &str) -> Result<ModpackItem, IpcError> {
        let payload = serde_json::json!({
            "name": name,
            "loader": loader,
            "mc_version": mc_version
        });
        let res: Value = self.call("modpack_create", payload).await?;
        let pack_val = if let Some(pack) = res.get("pack") {
            pack.clone()
        } else if let Some(data) = res.get("data") {
            data.clone()
        } else {
            res
        };
        Ok(serde_json::from_value(pack_val)?)
    }

    pub async fn link_modpack(&self, pack_id: &str, installation_id: &str) -> Result<bool, IpcError> {
        let payload = serde_json::json!({
            "pack_id": pack_id,
            "installation_id": installation_id
        });
        let res: Value = self.call("modpack_link", payload).await?;
        Ok(res.get("success").and_then(|v| v.as_bool()).unwrap_or(true))
    }

    pub async fn delete_modpack(&self, pack_id: &str) -> Result<bool, IpcError> {
        let payload = serde_json::json!({ "pack_id": pack_id });
        let res: Value = self.call("modpack_delete", payload).await?;
        Ok(res.get("success").and_then(|v| v.as_bool()).unwrap_or(true))
    }

    pub async fn export_modpack(&self, pack_id: &str, format: &str) -> Result<String, IpcError> {
        let payload = serde_json::json!({
            "pack_id": pack_id,
            "format": format
        });
        let res: Value = self.call("modpack_export", payload).await?;
        let path = res.get("path")
            .and_then(|v| v.as_str())
            .or_else(|| res.get("data").and_then(|d| d.get("path")).and_then(|v| v.as_str()))
            .unwrap_or("")
            .to_string();
        Ok(path)
    }

    pub async fn list_pack_mods(&self, pack_id: &str) -> Result<Vec<ModItem>, IpcError> {
        let payload = serde_json::json!({ "pack_id": pack_id });
        let res: Value = self.call("modpack_mods_list", payload).await?;
        let mods_val = if let Some(mods) = res.get("data") {
            mods.clone()
        } else if let Some(mods) = res.get("mods") {
            mods.clone()
        } else if res.is_array() {
            res
        } else {
            Value::Array(Vec::new())
        };
        Ok(serde_json::from_value(mods_val)?)
    }

    pub async fn toggle_pack_mod(&self, pack_id: &str, filename: &str, enabled: bool) -> Result<bool, IpcError> {
        let payload = serde_json::json!({
            "pack_id": pack_id,
            "filename": filename,
            "enabled": enabled
        });
        let res: Value = self.call("modpack_mods_toggle", payload).await?;
        Ok(res.get("success").and_then(|v| v.as_bool()).unwrap_or(true))
    }

    pub async fn remove_pack_mod(&self, pack_id: &str, filename: &str) -> Result<bool, IpcError> {
        let payload = serde_json::json!({
            "pack_id": pack_id,
            "filename": filename
        });
        let res: Value = self.call("modpack_mods_remove", payload).await?;
        Ok(res.get("success").and_then(|v| v.as_bool()).unwrap_or(true))
    }

    pub async fn install_pack_mod(&self, pack_id: &str, file_path: &str) -> Result<bool, IpcError> {
        let payload = serde_json::json!({
            "pack_id": pack_id,
            "file_path": file_path,
        });
        let res: Value = self.call("modpack_install_mod", payload).await?;
        Ok(res.get("status").and_then(|s| s.as_str()).unwrap_or("") == "success")
    }

    pub async fn list_versions(&self, loader: &str, include_snapshots: bool) -> Result<VersionManifestResponse, IpcError> {
        let payload = serde_json::json!({
            "loader": loader,
            "include_snapshots": include_snapshots,
        });
        let res: Value = self.call("versions_list", payload).await?;
        Ok(serde_json::from_value(res)?)
    }

    pub async fn list_loaders(&self) -> Result<LoadersResponse, IpcError> {
        let res: Value = self.call("loaders_list", Value::Null).await?;
        Ok(serde_json::from_value(res)?)
    }

    pub async fn get_modrinth_project(&self, project_id: &str) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "project_id": project_id });
        self.call("modrinth_project_details", payload).await
    }

    pub async fn install_modrinth_artifact(
        &self,
        project_id: &str,
        project_type: &str,
        target_id: &str,
        version_id: Option<&str>,
        url: Option<&str>,
        filename: Option<&str>,
        title: Option<&str>,
    ) -> Result<Value, IpcError> {
        let mut payload = serde_json::json!({
            "project_id": project_id,
            "project_type": project_type,
            "target_id": target_id,
            "version_id": version_id,
            "url": url,
            "filename": filename,
        });
        if let Some(t) = title {
            if !t.is_empty() {
                payload["title"] = serde_json::Value::String(t.to_string());
            }
        }
        self.call("modrinth_install_artifact", payload).await
    }

    pub async fn update_modpack(
        &self,
        pack_id: &str,
        name: Option<&str>,
        loader: Option<&str>,
        version: Option<&str>,
    ) -> Result<Value, IpcError> {
        let mut payload = serde_json::json!({ "pack_id": pack_id });
        if let Some(n) = name { payload["name"] = serde_json::Value::String(n.to_string()); }
        if let Some(l) = loader { payload["loader"] = serde_json::Value::String(l.to_string()); }
        if let Some(v) = version { payload["version"] = serde_json::Value::String(v.to_string()); }
        self.call("modpack_update", payload).await
    }

    pub async fn import_modpack(&self, archive_path: &str, name: Option<&str>) -> Result<ModpackItem, IpcError> {
        let payload = serde_json::json!({
            "archive_path": archive_path,
            "name": name,
        });
        let res: Value = self.call("modpack_import", payload).await?;
        if let Some(pack) = res.get("pack").or_else(|| res.get("data")) {
            Ok(serde_json::from_value(pack.clone())?)
        } else {
            Ok(serde_json::from_value(res)?)
        }
    }

    pub async fn install_modpack_mod(&self, pack_id: &str, file_path_or_url: &str) -> Result<Value, IpcError> {
        let is_url = file_path_or_url.starts_with("http://") || file_path_or_url.starts_with("https://");
        let payload = if is_url {
            serde_json::json!({ "pack_id": pack_id, "url": file_path_or_url })
        } else {
            serde_json::json!({ "pack_id": pack_id, "file_path": file_path_or_url })
        };
        self.call("modpack_install_mod", payload).await
    }

    pub async fn sync_skin(&self, req: SkinSyncRequest) -> Result<Value, IpcError> {
        self.call("gh_skin_sync", serde_json::to_value(req)?).await
    }

    pub async fn ping_server(&self, host: &str, port: u16) -> Result<ServerPingResponse, IpcError> {
        let payload = serde_json::json!({ "host": host, "port": port });
        self.call("server_ping", payload).await
    }

    pub async fn get_saved_servers(&self) -> Result<Vec<SavedServerItem>, IpcError> {
        let res: Value = self.call("addons_get_saved_servers", Value::Null).await?;
        if let Some(servers) = res.get("servers") {
            Ok(serde_json::from_value(servers.clone())?)
        } else if let Some(data) = res.get("data").and_then(|d| d.get("saved_servers")) {
            Ok(serde_json::from_value(data.clone())?)
        } else {
            Ok(vec![])
        }
    }

    pub async fn add_saved_server(&self, name: &str, address: &str, port: u16) -> Result<Vec<SavedServerItem>, IpcError> {
        let payload = serde_json::json!({ "name": name, "address": address, "port": port });
        let res: Value = self.call("addons_add_saved_server", payload).await?;
        if let Some(servers) = res.get("servers") {
            Ok(serde_json::from_value(servers.clone())?)
        } else if let Some(data) = res.get("data").and_then(|d| d.get("saved_servers")) {
            Ok(serde_json::from_value(data.clone())?)
        } else {
            Ok(vec![])
        }
    }

    pub async fn remove_saved_server(&self, server_id: &str) -> Result<Vec<SavedServerItem>, IpcError> {
        let payload = serde_json::json!({ "server_id": server_id });
        let res: Value = self.call("addons_remove_saved_server", payload).await?;
        if let Some(servers) = res.get("servers") {
            Ok(serde_json::from_value(servers.clone())?)
        } else if let Some(data) = res.get("data").and_then(|d| d.get("saved_servers")) {
            Ok(serde_json::from_value(data.clone())?)
        } else {
            Ok(vec![])
        }
    }

    pub async fn get_playtime_stats(&self) -> Result<PlaytimeStatsResponse, IpcError> {
        let res: Value = self.call("addons_get_playtime", Value::Null).await?;
        if let Some(data) = res.get("data") {
            Ok(serde_json::from_value(data.clone())?)
        } else {
            Ok(serde_json::from_value(res)?)
        }
    }

    pub async fn reset_playtime_stats(&self) -> Result<Value, IpcError> {
        self.call("addons_reset_playtime", Value::Null).await
    }

    pub async fn record_play_session(
        &self,
        inst_id: &str,
        seconds: u64,
        server_address: Option<&str>,
        server_port: Option<u16>,
    ) -> Result<Value, IpcError> {
        let payload = serde_json::json!({
            "inst_id": inst_id,
            "session_seconds": seconds,
            "server_address": server_address,
            "server_port": server_port,
        });
        self.call("addons_record_play_session", payload).await
    }

    pub async fn set_streamer_mode(&self, enabled: bool) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "enabled": enabled });
        self.call("addons_set_streamer_mode", payload).await
    }

    pub async fn list_screenshots(&self, minecraft_dir: Option<&str>) -> Result<ScreenshotListResponse, IpcError> {
        let payload = serde_json::json!({ "minecraft_dir": minecraft_dir });
        let res: Value = self.call("addons_list_screenshots", payload).await?;
        if let Some(data) = res.get("data") {
            Ok(serde_json::from_value(data.clone())?)
        } else {
            Ok(serde_json::from_value(res)?)
        }
    }

    pub async fn delete_screenshot(&self, path: &str, minecraft_dir: Option<&str>) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "path": path, "minecraft_dir": minecraft_dir });
        self.call("addons_delete_screenshot", payload).await
    }

    pub async fn get_diagnostics_system_info(&self) -> Result<SystemInfoResponse, IpcError> {
        let res: Value = self.call("diagnostics_get_system_info", Value::Null).await?;
        if let Some(data) = res.get("data") {
            Ok(serde_json::from_value(data.clone())?)
        } else {
            Ok(serde_json::from_value(res)?)
        }
    }

    pub async fn get_diagnostics_logs(&self) -> Result<DiagnosticsLogsResponse, IpcError> {
        self.call("diagnostics_get_logs", Value::Null).await
    }

    pub async fn set_diagnostic_logging(&self, enabled: bool) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "enabled": enabled });
        self.call("diagnostics_toggle_logging", payload).await
    }

    pub async fn reset_config_defaults(&self) -> Result<Value, IpcError> {
        self.call("config_reset_defaults", Value::Null).await
    }

    pub async fn open_folder(&self, target_or_path: &str) -> Result<Value, IpcError> {
        let payload = serde_json::json!({ "target": target_or_path });
        self.call("system_open_folder", payload).await
    }

    pub async fn list_third_party_addons(&self) -> Result<ListThirdPartyAddonsResponse, IpcError> {
        self.call("list_third_party_addons", serde_json::json!({})).await
    }

    pub async fn get_community_addons_catalog(&self) -> Result<Vec<Value>, IpcError> {
        let res: Value = self.call("addons_get_community_catalog", Value::Null).await?;
        if let Some(data) = res.get("data").and_then(|d| d.as_array()) {
            Ok(data.clone())
        } else {
            Ok(Vec::new())
        }
    }

    pub async fn run_third_party_addon_action(
        &self,
        addon_id: String,
        action_id: String,
        inputs: serde_json::Value,
    ) -> Result<RunThirdPartyAddonActionResponse, IpcError> {
        let payload = serde_json::json!({
            "addon_id": addon_id,
            "action_id": action_id,
            "inputs": inputs,
        });
        self.call("run_third_party_addon_action", payload).await
    }
}

// -----------------------------------------------------------------------------
// Third-Party Addons Data Models
// -----------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct AddonActionItem {
    pub id: String,
    #[serde(alias = "label", default)]
    pub name: String,
    #[serde(default)]
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct ThirdPartyAddonItem {
    pub id: String,
    pub name: String,
    #[serde(default = "default_addon_version")]
    pub version: String,
    #[serde(default = "default_addon_author")]
    pub author: String,
    #[serde(default)]
    pub description: String,
    #[serde(default = "default_addon_entrypoint")]
    pub entrypoint: String,
    #[serde(default)]
    pub actions: Vec<AddonActionItem>,
    #[serde(default)]
    pub folder_name: String,
    #[serde(default)]
    pub addon_dir: String,
    #[serde(default)]
    pub load_error: Option<String>,
}

fn default_addon_version() -> String {
    "1.0.0".to_string()
}
fn default_addon_author() -> String {
    "Unknown".to_string()
}
fn default_addon_entrypoint() -> String {
    "main.py".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct ListThirdPartyAddonsData {
    #[serde(default)]
    pub addons_dir: String,
    #[serde(default)]
    pub addons: Vec<ThirdPartyAddonItem>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct ListThirdPartyAddonsResponse {
    pub status: String,
    #[serde(default)]
    pub data: Option<ListThirdPartyAddonsData>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct RunThirdPartyAddonActionResponse {
    pub status: String,
    #[serde(default)]
    pub msg: Option<String>,
    #[serde(default)]
    pub data: Option<Value>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_rpc_wire_message_parsing() {
        let response_str = r#"{"id": "req-1", "result": {"status": "success"}, "error": null}"#;
        let msg: RpcWireMessage = serde_json::from_str(response_str).unwrap();
        assert_eq!(msg.id.as_deref(), Some("req-1"));
        assert!(msg.result.is_some());
        assert!(msg.error.is_none());

        let event_str = r#"{"event": "launch_state_changed", "payload": {"state": "downloading", "progress": 45.0}}"#;
        let event_msg: RpcWireMessage = serde_json::from_str(event_str).unwrap();
        assert_eq!(event_msg.id, None);
        assert_eq!(event_msg.event.as_deref(), Some("launch_state_changed"));
        assert_eq!(
            event_msg.payload.unwrap().get("state").and_then(|s| s.as_str()),
            Some("downloading")
        );
    }

    #[test]
    fn test_domain_models_serialization() {
        let launch_req = LaunchGameRequest {
            version: "1.20.4".to_string(),
            mock: Some(true),
            ram_mb: Some(4096),
            force_update: Some(true),
            ..Default::default()
        };
        let val = serde_json::to_value(&launch_req).unwrap();
        assert_eq!(val.get("version").and_then(|v| v.as_str()), Some("1.20.4"));
        assert_eq!(val.get("mock").and_then(|v| v.as_bool()), Some(true));
        assert_eq!(val.get("ram_mb").and_then(|v| v.as_u64()), Some(4096));
        assert_eq!(val.get("force_update").and_then(|v| v.as_bool()), Some(true));

        let acct_json = r#"[{"id": "1", "username": "Steve", "account_type": "offline", "active": true}]"#;
        let acct_resp: AccountsListResponse = serde_json::from_str(acct_json).unwrap();
        assert_eq!(acct_resp.accounts().len(), 1);
        assert_eq!(acct_resp.accounts()[0].name(), "Steve");
        assert_eq!(acct_resp.accounts()[0].account_type(), "offline");

        let acct_obj_json = r#"{"accounts": [{"id": "2", "name": "Alex", "type": "microsoft", "active": false}]}"#;
        let acct_obj_resp: AccountsListResponse = serde_json::from_str(acct_obj_json).unwrap();
        assert_eq!(acct_obj_resp.accounts().len(), 1);
        assert_eq!(acct_obj_resp.accounts()[0].name(), "Alex");
        assert_eq!(acct_obj_resp.accounts()[0].account_type(), "microsoft");

        let mod_json = r#"[{"name": "Sodium", "file": "sodium.jar", "enabled": true}]"#;
        let mod_resp: ModListResponse = serde_json::from_str(mod_json).unwrap();
        assert_eq!(mod_resp.mods().len(), 1);
        assert_eq!(mod_resp.mods()[0].name, "Sodium");

        let skin_json = r#"{"skin_path": "path/to/skin.png", "skin_model": "slim", "cape_path": ""}"#;
        let skin_resp: SkinInfoResponse = serde_json::from_str(skin_json).unwrap();
        assert_eq!(skin_resp.skin_path.as_deref(), Some("path/to/skin.png"));
        assert_eq!(skin_resp.skin_model.as_deref(), Some("slim"));
    }

    #[test]
    fn test_account_item_duplicate_keys() {
        let json_with_dups = r#"{
            "id": "1",
            "name": "CustomSteve",
            "username": "FallbackSteve",
            "type": "microsoft",
            "account_type": "offline",
            "active": true
        }"#;
        let item: AccountItem = serde_json::from_str(json_with_dups).expect("Should deserialize duplicate fields without error");
        assert_eq!(item.name(), "CustomSteve");
        assert_eq!(item.account_type(), "microsoft");

        let json_with_fallback = r#"{
            "username": "OnlyUsername",
            "account_type": "elyby"
        }"#;
        let item2: AccountItem = serde_json::from_str(json_with_fallback).expect("Should deserialize fallback fields");
        assert_eq!(item2.name(), "OnlyUsername");
        assert_eq!(item2.account_type(), "elyby");

        let json_empty = r#"{}"#;
        let item3: AccountItem = serde_json::from_str(json_empty).expect("Should deserialize empty json");
        assert_eq!(item3.name(), "Steve");
        assert_eq!(item3.account_type(), "offline");

        let json_whitespace = r#"{
            "name": "   ",
            "username": "  TrimmedName  ",
            "type": "   ",
            "account_type": "  microsoft  "
        }"#;
        let item4: AccountItem = serde_json::from_str(json_whitespace).expect("Should deserialize whitespace json");
        assert_eq!(item4.name(), "TrimmedName");
        assert_eq!(item4.account_type(), "microsoft");

        let json_extra_fields = r#"{
            "unknown_future_field": 42,
            "another_nested": {"foo": "bar"},
            "name": "Alex"
        }"#;
        let item5: AccountItem = serde_json::from_str(json_extra_fields).expect("Should ignore unknown extra fields");
        assert_eq!(item5.name(), "Alex");

        // AccountsListResponse Fallback tests
        let fallback_resp: AccountsListResponse = serde_json::from_str("null").unwrap_or(AccountsListResponse::Fallback);
        assert_eq!(fallback_resp.accounts().len(), 0);

        let weird_resp: AccountsListResponse = serde_json::from_str(r#"{"status": "ok", "unexpected": true}"#).unwrap();
        assert_eq!(weird_resp.accounts().len(), 0);
    }

    #[test]
    fn test_ipc_error_formatting() {
        let err = IpcError::AgentDisconnected("Process died".to_string());
        assert_eq!(format!("{}", err), "Agent disconnected: Process died");

        let srv_err = IpcError::ServerError {
            code: "ERR_TIMEOUT".to_string(),
            message: "Request timed out".to_string(),
            details: None,
        };
        assert_eq!(format!("{}", srv_err), "Server error [ERR_TIMEOUT]: Request timed out");
    }

    #[test]
    fn test_third_party_addons_models_serialization() {
        let json_raw = r#"{
            "status": "success",
            "data": {
                "addons_dir": "C:\\Users\\User\\.nlc\\addons",
                "addons": [
                    {
                        "id": "hello_addon",
                        "name": "Hello Addon",
                        "version": "1.0.0",
                        "author": "AmneDev",
                        "description": "Example third-party addon for New Launcher.",
                        "entrypoint": "main.py",
                        "actions": [
                            {
                                "id": "show_greeting",
                                "name": "Show Greeting",
                                "description": "Displays greeting message"
                            }
                        ],
                        "folder_name": "hello_addon",
                        "addon_dir": "C:\\Users\\User\\.nlc\\addons\\hello_addon",
                        "load_error": null
                    }
                ]
            }
        }"#;

        let resp: ListThirdPartyAddonsResponse = serde_json::from_str(json_raw).expect("Valid JSON");
        assert_eq!(resp.status, "success");
        assert!(resp.data.is_some());
        let data = resp.data.unwrap();
        assert_eq!(data.addons_dir, "C:\\Users\\User\\.nlc\\addons");
        assert_eq!(data.addons.len(), 1);
        let addon = &data.addons[0];
        assert_eq!(addon.id, "hello_addon");
        assert_eq!(addon.actions.len(), 1);
        assert_eq!(addon.actions[0].id, "show_greeting");
        assert_eq!(addon.actions[0].name, "Show Greeting");

        let action_resp_raw = r#"{"status": "success", "msg": "Action completed successfully"}"#;
        let action_resp: RunThirdPartyAddonActionResponse = serde_json::from_str(action_resp_raw).expect("Valid JSON");
        assert_eq!(action_resp.status, "success");
        assert_eq!(action_resp.msg.as_deref(), Some("Action completed successfully"));
    }
}

