@echo off
rem Bản dành cho nhà phát triển: có tab "Huấn luyện" (ADR-0004). Engine chạy từ engine\.venv trong repo,
rem nên thẻ học được ghi thẳng vào engine\knowledge để đẩy lên git.
rem Cần build trước một lần: cd app ^&^& npx tauri build --debug --no-bundle
start "" "%~dp0app\src-tauri\target\debug\guider.exe"
