//! Engine sidecar: spawn `kem serve`, forward stdout lines to the webview as `engine://line` events,
//! write requests to stdin. stderr (engine logs) goes to this process's stderr.

use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::Mutex;
use std::thread;

use tauri::{AppHandle, Emitter};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x0800_0000;

pub struct Engine {
    child: Mutex<Option<Child>>,
    stdin: Mutex<Option<ChildStdin>>,
    error: Mutex<Option<String>>,
}

/// Where the engine lives, in order: GUIDER_ENGINE (path to an executable that serves JSON-RPC when
/// given `serve`), a bundled `guider-engine.exe` next to the app (Phase 5 packaging), then the dev
/// venv in this repository.
fn engine_command() -> Option<(PathBuf, Vec<String>)> {
    if let Ok(p) = std::env::var("GUIDER_ENGINE") {
        return Some((PathBuf::from(p), vec!["serve".into()]));
    }
    if let Ok(exe) = std::env::current_exe() {
        let bundled = exe.with_file_name("guider-engine.exe");
        if bundled.exists() {
            return Some((bundled, vec!["serve".into()]));
        }
    }
    let dev = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("engine")
        .join(".venv")
        .join("Scripts")
        .join("kem.exe");
    dev.exists().then(|| (dev, vec!["serve".into()]))
}

impl Engine {
    pub fn spawn(app: AppHandle) -> Engine {
        let engine = Engine { child: Mutex::new(None), stdin: Mutex::new(None), error: Mutex::new(None) };
        let Some((program, args)) = engine_command() else {
            *engine.error.lock().unwrap() = Some("Không tìm thấy engine của Guider".into());
            return engine;
        };
        let mut cmd = Command::new(&program);
        cmd.args(&args).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(Stdio::inherit());
        #[cfg(windows)]
        cmd.creation_flags(CREATE_NO_WINDOW);
        match cmd.spawn() {
            Ok(mut child) => {
                let stdout = child.stdout.take().expect("piped stdout");
                *engine.stdin.lock().unwrap() = child.stdin.take();
                *engine.child.lock().unwrap() = Some(child);
                thread::spawn(move || {
                    for line in BufReader::new(stdout).lines() {
                        match line {
                            Ok(l) if !l.trim().is_empty() => {
                                let _ = app.emit("engine://line", l);
                            }
                            Ok(_) => {}
                            Err(_) => break,
                        }
                    }
                    let _ = app.emit("engine://exit", ());
                });
            }
            Err(e) => {
                *engine.error.lock().unwrap() = Some(format!("Không khởi động được engine ({}): {e}", program.display()));
            }
        }
        engine
    }

    pub fn send(&self, line: &str) -> Result<(), String> {
        if line.contains('\n') {
            return Err("one JSON object per line".into());
        }
        let mut guard = self.stdin.lock().unwrap();
        let stdin = guard.as_mut().ok_or_else(|| self.status())?;
        stdin
            .write_all(line.as_bytes())
            .and_then(|_| stdin.write_all(b"\n"))
            .and_then(|_| stdin.flush())
            .map_err(|e| format!("engine stdin: {e}"))
    }

    pub fn status(&self) -> String {
        if let Some(e) = self.error.lock().unwrap().as_ref() {
            return e.clone();
        }
        match self.child.lock().unwrap().as_mut().map(|c| c.try_wait()) {
            Some(Ok(None)) => "running".into(),
            Some(Ok(Some(code))) => format!("Engine đã dừng ({code})"),
            _ => "Engine chưa chạy".into(),
        }
    }

    pub fn shutdown(&self) {
        // Closing stdin ends `kem serve`'s read loop; the engine tears down any open sandbox itself.
        self.stdin.lock().unwrap().take();
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let deadline = std::time::Instant::now() + std::time::Duration::from_secs(20);
            while std::time::Instant::now() < deadline {
                if let Ok(Some(_)) = child.try_wait() {
                    return;
                }
                thread::sleep(std::time::Duration::from_millis(200));
            }
            let _ = child.kill();
        }
    }
}
