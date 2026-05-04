use std::sync::Mutex;
use tauri::Manager;
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};

struct BackendProcess(Mutex<Option<CommandChild>>);
struct OllamaProcess(Mutex<Option<std::process::Child>>);

fn find_ollama_binary() -> Option<String> {
    let candidates = [
        "/usr/local/bin/ollama",
        "/opt/homebrew/bin/ollama",
        "/opt/local/bin/ollama",
    ];
    candidates
        .iter()
        .find(|p| std::path::Path::new(p).exists())
        .map(|p| p.to_string())
}

fn ollama_already_running() -> bool {
    std::net::TcpStream::connect_timeout(
        &"127.0.0.1:11434".parse().unwrap(),
        std::time::Duration::from_millis(300),
    )
    .is_ok()
}

#[tauri::command]
fn check_ollama_installed() -> bool {
    find_ollama_binary().is_some()
}

#[tauri::command]
fn quit_app(
    backend: tauri::State<BackendProcess>,
    ollama: tauri::State<OllamaProcess>,
) {
    if let Ok(mut guard) = backend.0.lock() {
        if let Some(child) = guard.take() {
            let _ = child.kill();
        }
    }
    if let Ok(mut guard) = ollama.0.lock() {
        if let Some(mut child) = guard.take() {
            let _ = child.kill();
        }
    }
    std::process::exit(0);
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![quit_app, check_ollama_installed])
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }

            let data_dir = app.path().app_data_dir()?;
            std::fs::create_dir_all(&data_dir)?;

            let sidecar = app.shell().sidecar("telmi-backend")?;
            let (mut rx, child) = sidecar
                .env("TELMI_DATA_DIR", data_dir.to_string_lossy().as_ref())
                .spawn()?;

            // Drain the sidecar's stdout/stderr in a background task so the
            // pipe never blocks and we can see output in the dev terminal.
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(line) => {
                            print!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Stderr(line) => {
                            eprint!("[sidecar] {}", String::from_utf8_lossy(&line));
                        }
                        CommandEvent::Terminated(payload) => {
                            eprintln!(
                                "[sidecar] process terminated — code: {:?}, signal: {:?}",
                                payload.code, payload.signal
                            );
                            break;
                        }
                        _ => {}
                    }
                }
            });

            app.manage(BackendProcess(Mutex::new(Some(child))));

            // Auto-start Ollama if installed but not already running
            let ollama_child: Option<std::process::Child> = if let Some(binary) = find_ollama_binary() {
                if !ollama_already_running() {
                    std::process::Command::new(&binary)
                        .arg("serve")
                        .stdout(std::process::Stdio::null())
                        .stderr(std::process::Stdio::null())
                        .spawn()
                        .ok()
                } else {
                    None
                }
            } else {
                None
            };
            app.manage(OllamaProcess(Mutex::new(ollama_child)));

            #[cfg(target_os = "macos")]
            {
                use window_vibrancy::{apply_vibrancy, NSVisualEffectMaterial};
                if let Some(win) = app.get_webview_window("main") {
                    let _ = apply_vibrancy(&win, NSVisualEffectMaterial::Sidebar, None, None);
                }
            }

            Ok(())
        })
        .on_window_event(|_window, _event| {})
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
