//! Guider desktop shell: hosts the web UI and relays JSON-RPC lines to the Python engine over stdio
//! (SPEC ADR-6, §11). No network port is opened; only this process can talk to the engine.

mod engine;

use engine::Engine;
use tauri::Manager;

#[tauri::command]
fn engine_send(line: String, engine: tauri::State<'_, Engine>) -> Result<(), String> {
    engine.send(&line)
}

#[tauri::command]
fn engine_status(engine: tauri::State<'_, Engine>) -> String {
    engine.status()
}

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init()) // "Chọn file của bạn" (ADR-0003): open dialog only
        .setup(|app| {
            let engine = Engine::spawn(app.handle().clone());
            app.manage(engine);
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![engine_send, engine_status])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(engine) = window.app_handle().try_state::<Engine>() {
                    engine.shutdown();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running Guider");
}
