//! Adversarial Rust IPC integration test harness
//! Stress-tests AgentClient concurrency, event streams, and error resilience.

#[path = "../src/ipc.rs"]
mod ipc;

use ipc::{AgentClient, IpcError, LaunchGameRequest, RpcEvent};
use serde_json::{json, Value};
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::broadcast;
use tokio::time::timeout;


fn get_project_root() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("Parent repo root")
        .to_path_buf()
}

fn kill_pid(pid: u32) {
    #[cfg(windows)]
    {
        let output = std::process::Command::new("taskkill")
            .args(["/F", "/PID", &pid.to_string()])
            .output()
            .expect("Failed to run taskkill");
        assert!(output.status.success(), "taskkill failed: {:?}", output);
    }
    #[cfg(not(windows))]
    {
        let output = std::process::Command::new("kill")
            .args(["-9", &pid.to_string()])
            .output()
            .expect("Failed to run kill");
        assert!(output.status.success(), "kill -9 failed: {:?}", output);
    }
}

#[tokio::test]
async fn test_rust_ipc_100_concurrent_requests() {
    let root = get_project_root();
    let client = AgentClient::spawn(root)
        .await
        .expect("AgentClient spawn failed");

    // Ping first to ensure child is fully ready
    assert!(client.ping().await, "Initial ping failed");

    let count = 100;
    let success_count = Arc::new(AtomicUsize::new(0));
    let mut handles = Vec::with_capacity(count);

    for i in 0..count {
        let client_clone = client.clone();
        let counter = success_count.clone();

        handles.push(tokio::spawn(async move {
            let res = if i % 2 == 0 {
                client_clone.ping().await
            } else {
                client_clone.get_config().await.is_ok()
            };
            if res {
                counter.fetch_add(1, Ordering::SeqCst);
            }
        }));
    }

    // Await all 100 concurrent tasks with an overall timeout of 15 seconds
    let join_result = timeout(Duration::from_secs(15), async {
        for handle in handles {
            handle.await.expect("Task panicked");
        }
    })
    .await;

    assert!(
        join_result.is_ok(),
        "Concurrent requests deadlocked or timed out"
    );

    let finished = success_count.load(Ordering::SeqCst);
    assert_eq!(
        finished, count,
        "Expected all 100 concurrent requests to succeed, but only {} succeeded",
        finished
    );
}

#[tokio::test]
async fn test_rust_ipc_concurrency_with_event_stream() {
    let root = get_project_root();
    let client = AgentClient::spawn(root)
        .await
        .expect("AgentClient spawn failed");

    let mut event_rx = client.subscribe_events();

    // Trigger mock launch to start background event generation
    let launch_res = client
        .launch_game(LaunchGameRequest {
            version: "mock".to_string(),
            mock: Some(true),
            ..Default::default()
        })
        .await
        .expect("Launch game request failed");

    assert_eq!(launch_res.status, "launching");

    // Concurrently fire 50 calls while events are streaming
    let count = 50;
    let mut handles = Vec::with_capacity(count);
    for _ in 0..count {
        let client_clone = client.clone();
        handles.push(tokio::spawn(async move {
            client_clone.ping().await
        }));
    }

    // Also concurrently listen to events
    let event_count = Arc::new(AtomicUsize::new(0));
    let event_counter = event_count.clone();
    let listener_handle = tokio::spawn(async move {
        while let Ok(evt) = event_rx.recv().await {
            if evt.event == "launch_state_changed" {
                event_counter.fetch_add(1, Ordering::SeqCst);
            }
            if evt.event == "game_session_ended" {
                break;
            }
        }
    });

    let join_result = timeout(Duration::from_secs(10), async {
        for handle in handles {
            assert!(handle.await.unwrap(), "Interleaved ping failed");
        }
    })
    .await;

    assert!(join_result.is_ok(), "Interleaved pings timed out");

    // Wait briefly for launch events
    let _ = timeout(Duration::from_secs(4), listener_handle).await;
    assert!(
        event_count.load(Ordering::SeqCst) > 0,
        "No launch_state_changed events received"
    );
}

/// Helper to create a temporary test directory
fn create_test_dir(name: &str) -> PathBuf {
    let mut dir = std::env::temp_dir();
    dir.push(format!("nlc_test_{}_{}", name, std::process::id()));
    let _ = fs::remove_dir_all(&dir);
    fs::create_dir_all(&dir).expect("Failed to create test dir");
    dir
}

#[tokio::test]
async fn test_sudden_child_kill_resolves_pending_callers_without_hanging() {
    let test_dir = create_test_dir("sudden_kill");
    let pid_file = test_dir.join("agent.pid");
    let agent_script = test_dir.join("agent.py");

    let script_content = r#"
import sys, json, os, time

pid_file = os.path.join(os.path.dirname(__file__), "agent.pid")
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))

sys.stdout.write("Agent process started.\n")
sys.stdout.flush()

while True:
    line = sys.stdin.readline()
    if not line:
        break
    try:
        req = json.loads(line)
        action = req.get("action")
        req_id = req.get("id")
        if action == "fast":
            resp = {"id": req_id, "result": {"status": "ok"}, "error": None}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
        elif action == "hang":
            time.sleep(60)
    except Exception:
        pass
"#;
    fs::write(&agent_script, script_content).expect("Failed to write mock agent");

    let client = AgentClient::spawn(test_dir.clone())
        .await
        .expect("Failed to spawn AgentClient");

    let mut event_rx = client.subscribe_events();

    // Verify initial communication works
    let fast_resp: Value = client
        .call("fast", json!({}))
        .await
        .expect("Fast call should succeed");
    assert_eq!(fast_resp.get("status").and_then(|s| s.as_str()), Some("ok"));

    // Launch 5 concurrent calls that will hang waiting for response
    let num_pending = 5;
    let mut handles = Vec::new();
    for i in 0..num_pending {
        let client_clone = client.clone();
        let handle = tokio::spawn(async move {
            let start = std::time::Instant::now();
            let result: Result<Value, IpcError> = client_clone.call("hang", json!({"idx": i})).await;
            (start.elapsed(), result)
        });
        handles.push(handle);
    }

    // Give requests time to reach stdin and be registered in pending_requests
    tokio::time::sleep(Duration::from_millis(150)).await;

    // Read PID and kill the process abruptly via taskkill
    let pid_str = fs::read_to_string(&pid_file).expect("Failed to read agent PID");
    let pid: u32 = pid_str.trim().parse().expect("Invalid PID");

    println!("[TEST] Killing agent process PID {} while 5 requests are pending...", pid);
    kill_pid(pid);

    // Verify all pending callers resolve promptly with AgentDisconnected and DO NOT HANG
    for (idx, handle) in handles.into_iter().enumerate() {
        let call_res = timeout(Duration::from_secs(2), handle).await;
        assert!(call_res.is_ok(), "Caller {} hung and timed out after process kill!", idx);

        let (elapsed, res) = call_res.unwrap().expect("Task panicked");
        println!("[TEST] Caller {} resolved after {:?} with result: {:?}", idx, elapsed, res);

        match res {
            Err(IpcError::AgentDisconnected(msg)) => {
                assert!(
                    msg.contains("Agent process exited"),
                    "Expected AgentDisconnected message, got: {}",
                    msg
                );
            }
            other => panic!("Expected Err(IpcError::AgentDisconnected), got {:?}", other),
        }
    }

    // Verify agent_disconnected event was emitted on broadcast channel
    let evt_res = timeout(Duration::from_secs(1), event_rx.recv()).await;
    assert!(evt_res.is_ok(), "Did not receive agent_disconnected event in time");
    let evt = evt_res.unwrap().expect("Event channel closed prematurely");
    assert_eq!(evt.event, "agent_disconnected");

    let _ = fs::remove_dir_all(&test_dir);
}

#[tokio::test]
async fn test_subsequent_calls_after_agent_kill_fail_immediately() {
    let test_dir = create_test_dir("post_kill");
    let pid_file = test_dir.join("agent.pid");
    let agent_script = test_dir.join("agent.py");

    let script_content = r#"
import sys, json, os

pid_file = os.path.join(os.path.dirname(__file__), "agent.pid")
with open(pid_file, "w") as f:
    f.write(str(os.getpid()))

sys.stdout.write("Agent process started.\n")
sys.stdout.flush()

while True:
    line = sys.stdin.readline()
    if not line:
        break
"#;
    fs::write(&agent_script, script_content).expect("Failed to write mock agent");

    let client = AgentClient::spawn(test_dir.clone())
        .await
        .expect("Failed to spawn AgentClient");

    let mut pid_str = String::new();
    for _ in 0..60 {
        if let Ok(s) = fs::read_to_string(&pid_file) {
            if !s.trim().is_empty() {
                pid_str = s;
                break;
            }
        }
        tokio::time::sleep(Duration::from_millis(50)).await;
    }
    assert!(!pid_str.is_empty(), "agent.pid was not written within 3s");
    let pid: u32 = pid_str.trim().parse().expect("Invalid PID");
    kill_pid(pid);

    tokio::time::sleep(Duration::from_millis(100)).await;

    // Verify subsequent calls do NOT hang; they must fail immediately
    let res = timeout(Duration::from_millis(500), client.call::<Value>("ping", json!({}))).await;
    assert!(res.is_ok(), "Post-death call hung and timed out!");
    assert!(res.unwrap().is_err(), "Post-death call should have returned an Err");

    let _ = fs::remove_dir_all(&test_dir);
}

#[tokio::test]
async fn test_broadcast_burst_500_events_no_panic() {
    let test_dir = create_test_dir("burst_500");
    let agent_script = test_dir.join("agent.py");

    let script_content = r#"
import sys, json

sys.stdout.write("Agent process started.\n")
sys.stdout.flush()

while True:
    line = sys.stdin.readline()
    if not line:
        break
    try:
        req = json.loads(line)
        action = req.get("action")
        req_id = req.get("id")
        if action == "emit_burst":
            count = req.get("payload", {}).get("count", 500)
            for i in range(count):
                evt = {"event": "burst_event", "payload": {"seq": i}}
                sys.stdout.write(json.dumps(evt) + "\n")
            sys.stdout.flush()
            resp = {"id": req_id, "result": {"sent": count}, "error": None}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
    except Exception as e:
        pass
"#;
    fs::write(&agent_script, script_content).expect("Failed to write burst agent");

    let client = AgentClient::spawn(test_dir.clone())
        .await
        .expect("Failed to spawn AgentClient");

    let mut event_rx = client.subscribe_events();

    let burst_count = 500;
    let call_handle = tokio::spawn({
        let client = client.clone();
        async move {
            client
                .call::<Value>("emit_burst", json!({"count": burst_count}))
                .await
        }
    });

    let mut received = 0;
    let mut lagged = 0;

    let receive_timeout = timeout(Duration::from_secs(5), async {
        while received + lagged < burst_count {
            match event_rx.recv().await {
                Ok(evt) => {
                    assert_eq!(evt.event, "burst_event");
                    received += 1;
                }
                Err(broadcast::error::RecvError::Lagged(n)) => {
                    lagged += n as usize;
                }
                Err(broadcast::error::RecvError::Closed) => {
                    break;
                }
            }
        }
    })
    .await;

    assert!(receive_timeout.is_ok(), "Timed out receiving 500 burst events");
    assert_eq!(
        received + lagged,
        burst_count,
        "Total received ({}) + lagged ({}) should equal sent ({})",
        received,
        lagged,
        burst_count
    );
    println!(
        "[TEST] 500 Burst completed: received directly={}, lagged skipped={}",
        received, lagged
    );

    let call_res = call_handle.await.expect("Call task panicked").expect("Call failed");
    assert_eq!(call_res.get("sent").and_then(|s| s.as_u64()), Some(500));

    let _ = fs::remove_dir_all(&test_dir);
}

#[tokio::test]
async fn test_broadcast_channel_overflow_lag_recovery() {
    let (tx, _) = broadcast::channel::<RpcEvent>(512);
    let mut rx = tx.subscribe();

    let overflow_count = 700;
    for i in 0..overflow_count {
        tx.send(RpcEvent {
            event: "flood".to_string(),
            payload: json!({"seq": i}),
        })
        .expect("Send should succeed while receivers exist");
    }

    match rx.recv().await {
        Err(broadcast::error::RecvError::Lagged(missed)) => {
            println!("[TEST] Successfully caught broadcast lag: missed {} events", missed);
            assert!(missed > 0, "Expected missed events count > 0");
            assert_eq!(missed, 188);
        }
        other => panic!("Expected RecvError::Lagged, got {:?}", other),
    }

    let next_evt = rx.recv().await.expect("Next event should succeed after lag");
    assert_eq!(next_evt.event, "flood");
    let seq = next_evt.payload.get("seq").and_then(|s| s.as_u64()).unwrap();
    assert_eq!(seq, 188);

    tx.send(RpcEvent {
        event: "fresh".to_string(),
        payload: json!({"status": "ok"}),
    })
    .unwrap();

    let mut found_fresh = false;
    while let Ok(evt) = rx.recv().await {
        if evt.event == "fresh" {
            found_fresh = true;
            break;
        }
    }
    assert!(found_fresh, "Receiver successfully recovered and read fresh event");
}

#[tokio::test]
async fn test_kill_game_and_real_agent_lifecycle() {
    let repo_root = PathBuf::from("c:/Projects/New-launcher");
    if !repo_root.join("agent.py").exists() {
        eprintln!("[TEST] Skipped: repo agent.py not found at expected path");
        return;
    }

    let client = AgentClient::spawn(repo_root)
        .await
        .expect("Failed to connect to repo agent.py");

    assert!(client.ping().await, "Agent ping should succeed");

    let kill_res: Result<Value, IpcError> = client
        .call("kill_game", json!({"launch_id": "non_existent_uuid"}))
        .await;
    println!("[TEST] kill_game on inactive launch returned: {:?}", kill_res);
    match kill_res {
        Ok(v) => assert_eq!(v.get("status").and_then(|s| s.as_str()), Some("error")),
        Err(IpcError::ServerError { code, .. }) => assert_eq!(code, "ERR_BACKEND"),
        Err(e) => panic!("Unexpected error on kill_game: {:?}", e),
    }

    let launch_req = LaunchGameRequest {
        version: "mock".to_string(),
        mock: Some(true),
        ..Default::default()
    };
    let launch_resp = client
        .launch_game(launch_req)
        .await
        .expect("Mock launch should initiate");
    assert_eq!(launch_resp.status, "launching");
    let launch_id = launch_resp.launch_id.expect("Expected launch_id");

    let kill_active: Result<Value, IpcError> = client
        .call("kill_game", json!({"launch_id": launch_id}))
        .await;
    println!("[TEST] kill_game on mock launch returned: {:?}", kill_active);
}
