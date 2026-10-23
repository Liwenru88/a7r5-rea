#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod runtime;
mod tasks;
use serde_json::Value;
use std::{
    path::{Path, PathBuf},
    sync::Arc,
};
use tauri::Manager;
use tauri_plugin_dialog::DialogExt;

type AppState = Arc<tasks::State>;
#[tauri::command]
fn overview(state: tauri::State<AppState>) -> Result<Value, String> {
    tasks::overview(&state).map_err(|e| e.to_string())
}
#[tauri::command]
async fn start_task(
    state: tauri::State<'_, AppState>,
    input: tasks::Input,
) -> Result<String, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || tasks::start(state, input))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}
#[tauri::command]
async fn recover_task(state: tauri::State<'_, AppState>, id: String) -> Result<Value, String> {
    let state = state.inner().clone();
    tauri::async_runtime::spawn_blocking(move || tasks::recover(&state, &id))
        .await
        .map_err(|e| e.to_string())?
        .map_err(|e| e.to_string())
}
#[tauri::command]
fn confirm_screen(state: tauri::State<AppState>, id: String) -> Result<(), String> {
    tasks::confirm(&state, &id).map_err(|e| e.to_string())
}
#[tauri::command]
fn reveal_task(state: tauri::State<AppState>, id: String, guide: bool) -> Result<(), String> {
    tasks::reveal(&state, &id, guide).map_err(|e| e.to_string())
}
#[tauri::command]
async fn choose_path(app: tauri::AppHandle, kind: String) -> Result<Option<String>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let dialog = app.dialog().file();
        let value = match kind.as_str() {
            "source" => dialog
                .set_title("选择适配的官方4.00 BODYDATA.DAT")
                .add_filter("固件", &["DAT", "dat"])
                .blocking_pick_file(),
            "backup" => dialog
                .set_title("选择备份任务中的 result.json")
                .add_filter("备份记录", &["json"])
                .blocking_pick_file(),
            "output" => dialog
                .set_title("另存自定义更新包")
                .set_file_name("BODYDATA.DAT")
                .add_filter("固件", &["DAT"])
                .blocking_save_file(),
            _ => return Err("文件选择类型无效".to_owned()),
        };
        value
            .map(|p| {
                p.into_path()
                    .map(|p| p.to_string_lossy().into_owned())
                    .map_err(|e| e.to_string())
            })
            .transpose()
    })
    .await
    .map_err(|e| e.to_string())?
}

fn cli() -> anyhow::Result<bool> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        return Ok(false);
    }
    match args[0].as_str() {
        "--selfcheck" if args.len() == 1 => {
            let root = runtime::engine()?;
            runtime::verify(&root)?;
            println!("{}", runtime::execute(&root, "selfcheck", None, None)?);
        }
        "--privileged-task" if args.len() == 2 => runtime::privileged(Path::new(&args[1]))?,
        "--build-firmware" if args.len() == 3 => {
            let root = runtime::engine()?;
            runtime::verify(&root)?;
            let job = PathBuf::from(&args[2]);
            runtime::ordinary(&job, false)?;
            std::fs::create_dir(&job)?;
            println!(
                "{}",
                runtime::execute(&root, "firmware", Some(Path::new(&args[1])), Some(&job))?
            );
        }
        _ => anyhow::bail!("命令格式无效"),
    };
    Ok(true)
}

fn main() {
    match cli() {
        Ok(true) => return,
        Err(e) => {
            eprintln!("{e:#}");
            std::process::exit(1)
        }
        Ok(false) => {}
    }
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            let data = app.path().app_data_dir()?;
            let state = tasks::init(data)?;
            let lock = runtime::lock(&state.data.join("application.lock"))?;
            app.manage(lock);
            app.manage(Arc::new(state));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            overview,
            start_task,
            choose_path,
            recover_task,
            confirm_screen,
            reveal_task
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if let Some(s) = window.try_state::<AppState>() {
                    if s.busy.lock().map(|b| *b).unwrap_or(true) {
                        api.prevent_close();
                    }
                }
            }
        })
        .build(tauri::generate_context!());
    match app {
        Ok(app) => app.run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if let Some(state) = app.try_state::<AppState>() {
                    if state.busy.lock().map(|b| *b).unwrap_or(true) {
                        api.prevent_exit();
                    }
                }
            }
        }),
        Err(e) => {
            eprintln!("客户端启动失败：{e}");
            std::process::exit(1)
        }
    }
}
