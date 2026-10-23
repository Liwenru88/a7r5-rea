use crate::runtime as rt;
use anyhow::{bail, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::{Arc, Mutex},
};

pub struct State {
    pub data: PathBuf,
    pub engine: PathBuf,
    pub busy: Mutex<bool>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Input {
    kind: String,
    source: Option<String>,
    output: Option<String>,
    features: Option<Value>,
    version: Option<String>,
    backup_manifest: Option<String>,
    password: Option<String>,
}

pub fn init(data: PathBuf) -> Result<State> {
    rt::ordinary(&data, false)?;
    fs::create_dir_all(data.join("tasks"))?;
    fs::set_permissions(&data, fs::Permissions::from_mode(0o700))?;
    fs::set_permissions(data.join("tasks"), fs::Permissions::from_mode(0o700))?;
    Ok(State {
        data,
        engine: rt::engine()?,
        busy: Mutex::new(false),
    })
}

fn id(value: &str) -> Result<()> {
    if value.len() != 32
        || !value
            .bytes()
            .all(|c| c.is_ascii_hexdigit() && !c.is_ascii_uppercase())
    {
        bail!("任务编号无效")
    };
    Ok(())
}
fn job(state: &State, value: &str) -> Result<PathBuf> {
    id(value)?;
    let path = state.data.join("tasks").join(value);
    rt::ordinary(&path, false)?;
    Ok(path)
}
fn status(dir: &Path, value: &Value) -> Result<()> {
    let path = dir.join("status.json");
    let tmp = dir.join(format!("status-{}.tmp", uuid::Uuid::new_v4().simple()));
    rt::private_json(&tmp, value)?;
    fs::rename(tmp, path)?;
    Ok(())
}

pub fn overview(state: &State) -> Result<Value> {
    let busy = state
        .busy
        .lock()
        .map_err(|_| anyhow::anyhow!("任务状态锁异常"))?;
    let pending = state.data.join("pending.json");
    let active = state.data.join("active-ssh.json");
    let mut tasks = Vec::new();
    for row in fs::read_dir(state.data.join("tasks"))? {
        let directory = row?.path();
        let path = directory.join("status.json");
        if path.exists() {
            let mut value = rt::read_json(&path)?;
            if !*busy && (value["running"] == true || value["interrupted"] == true) {
                let helper = directory.join("privileged-result.json");
                let plain = directory.join("result.json");
                let result = if helper.exists() {
                    Some(rt::read_json(&helper)?)
                } else if plain.exists() {
                    Some(rt::read_json(&plain)?)
                } else {
                    None
                };
                value["running"] = json!(false);
                value["interrupted"] = json!(result.is_none());
                value["result"]=result.unwrap_or_else(||json!({"task_complete":false,"can_replug":false,"error":"应用曾中断，结果尚未取得。保留连接与待恢复记录，不自动重试；后续回执到达时会自动载入。"}));
                status(&directory, &value)?;
            }
            tasks.push(value);
        }
    }
    tasks.sort_by_key(|v| std::cmp::Reverse(v["created"].as_u64().unwrap_or(0)));
    tasks.truncate(25);
    Ok(json!({"busy":*busy,
        "pending":if pending.exists(){rt::read_json(&pending)?}else{Value::Null},
        "active_ssh":active.exists(),"tasks":tasks,"data":state.data,"test_package":true}))
}

fn validate(input: &Input) -> Result<()> {
    if !["firmware", "backup", "update", "ssh_start", "ssh_stop"].contains(&input.kind.as_str()) {
        bail!("不支持的任务")
    }
    if input.kind == "firmware" {
        let source = input.source.as_deref().context("请选择官方固件")?;
        rt::ordinary(Path::new(source), true)?;
        let output = input.output.as_deref().context("请选择输出位置")?;
        rt::ordinary(Path::new(output), false)?;
        let flags = input
            .features
            .as_ref()
            .and_then(Value::as_object)
            .context("功能选择无效")?;
        if flags.len() != 4
            || ["fl23", "looks", "ntsc", "sound"]
                .iter()
                .any(|k| !flags.get(*k).is_some_and(Value::is_boolean))
        {
            bail!("功能选择无效")
        }
        if let Some(version) = &input.version {
            let valid = version.split_once('.').is_some_and(|(a, b)| {
                (1..=2).contains(&a.len())
                    && b.len() == 2
                    && a.bytes().chain(b.bytes()).all(|c| c.is_ascii_digit())
            });
            if !valid {
                bail!("输出包版本格式应为4.06；它只标记容器，不代表相应官方固件功能")
            }
        }
    }
    if input.kind == "update" {
        rt::ordinary(
            Path::new(
                input
                    .backup_manifest
                    .as_deref()
                    .context("请选择真实备份记录")?,
            ),
            true,
        )?;
    }
    if input.kind == "ssh_start" && input.password.is_none() {
        bail!("请输入相机SSH密码")
    }
    Ok(())
}

pub fn start(state: Arc<State>, mut input: Input) -> Result<String> {
    validate(&input)?;
    let mut busy = state
        .busy
        .lock()
        .map_err(|_| anyhow::anyhow!("任务锁异常"))?;
    if *busy {
        bail!("已有任务正在执行")
    }
    let device = input.kind != "firmware";
    if device && state.data.join("pending.json").exists() {
        bail!("上次设备任务尚未确认结束，请先查看该任务")
    }
    if device && state.data.join("active-ssh.json").exists() && input.kind != "ssh_stop" {
        bail!("请先停止当前SSH实例并确认相机恢复")
    }
    rt::verify(&state.engine)?;
    let run_id = uuid::Uuid::new_v4().simple().to_string();
    let dir = job(&state, &run_id)?;
    fs::DirBuilder::new().mode(0o700).create(&dir)?;
    let mut request = json!({"kind":input.kind,"run_id":run_id});
    if input.kind == "firmware" {
        request["source"] = json!(input.source);
        request["output"] = json!(input.output);
        request["features"] = json!(input.features);
        request["version"] = json!(input.version);
    }
    if input.kind == "update" {
        request["backup_manifest"] = json!(input.backup_manifest);
    }
    if input.kind == "ssh_start" {
        request["password_hash"] = json!(rt::password_hash(
            input.password.take().context("缺少SSH密码")?
        )?);
    }
    if input.kind == "ssh_stop" {
        request["active"] = rt::read_json(&state.data.join("active-ssh.json"))?;
    }
    rt::private_json(&dir.join("request.json"), &request)?;
    let created = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)?
        .as_secs();
    let initial = json!({"id":run_id,"kind":input.kind,"created":created,"running":true,"message":if device{"等待macOS管理员授权；取消将不会启动设备操作"}else{"正在验证并封装固件，可能需要几分钟"},"directory":dir});
    status(&dir, &initial)?;
    if device {
        rt::private_json(
            &state.data.join("pending.json"),
            &json!({"id":run_id,"kind":input.kind}),
        )?;
    }
    *busy = true;
    drop(busy);
    let thread_state = state.clone();
    let thread_id = run_id.clone();
    std::thread::spawn(move || {
        let outcome = (|| -> Result<Value> {
            if !device {
                return rt::execute(
                    &thread_state.engine,
                    "firmware",
                    Some(&dir.join("request.json")),
                    Some(&dir),
                );
            }
            let exe = std::env::current_exe()?;
            let shell = format!(
                "{} --privileged-task {}",
                rt::quote(exe.to_str().context("应用路径无效")?),
                rt::quote(dir.join("request.json").to_str().context("请求路径无效")?)
            );
            let script=format!("do shell script {} with administrator privileges with prompt {}",serde_json::to_string(&shell)?,serde_json::to_string("A7R5 Studio需要管理员权限接管USB连接。请输入这台Mac的登录密码；相机SSH密码与此无关。")?);
            let out = Command::new("/usr/bin/osascript")
                .env_clear()
                .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
                .args(["-e", &script])
                .stdin(Stdio::null())
                .output()?;
            fs::write(dir.join("authorization.log"), &out.stderr)?;
            if dir.join("privileged-result.json").exists() {
                return rt::read_json(&dir.join("privileged-result.json"));
            }
            if String::from_utf8_lossy(&out.stderr).contains("(-128)") {
                return Ok(
                    json!({"task_complete":false,"device_IO":false,"can_replug":true,"error":"系统授权已取消，设备操作未开始"}),
                );
            }
            bail!("授权助手没有完整结果，保留任务锁和连接；请查看日志，禁止自动重试")
        })();
        let result = outcome.unwrap_or_else(
            |e| json!({"error":e.to_string(),"task_complete":false,"can_replug":false}),
        );
        let finished = json!({"id":thread_id,"kind":input.kind,"created":created,"running":false,"result":result,"directory":dir});
        let _ = rt::private_json(&dir.join("result.json"), &result);
        let _ = status(&dir, &finished);
        if device && result["device_IO"] == false {
            let _ = rt::private_json(
                &dir.join("no-device-operation.json"),
                &json!({"confirmed":true}),
            );
            let _ = fs::remove_file(thread_state.data.join("pending.json"));
        }
        if let Ok(mut busy) = thread_state.busy.lock() {
            *busy = false;
        }
    });
    Ok(run_id)
}

pub fn recover(state: &State, task_id: &str) -> Result<Value> {
    let _busy = state
        .busy
        .lock()
        .map_err(|_| anyhow::anyhow!("任务锁异常"))?;
    if *_busy {
        bail!("请等待当前任务结束")
    }
    let pending = rt::read_json(&state.data.join("pending.json"))?;
    if pending["id"] != task_id {
        bail!("恢复任务不匹配")
    }
    let dir = job(state, task_id)?;
    let mut current = rt::read_json(&dir.join("status.json"))?;
    let result = &current["result"];
    if result["task_complete"] != true {
        bail!("机内任务未核实完成，请保持连接并查看失败记录")
    }
    let recovery = dir.join(format!("recovery-{}", uuid::Uuid::new_v4().simple()));
    fs::create_dir(&recovery)?;
    rt::private_json(&recovery.join("request.json"), &json!({"previous":result}))?;
    let value = rt::execute(
        &state.engine,
        "recovery",
        Some(&recovery.join("request.json")),
        Some(&recovery),
    )?;
    current["result"] = value;
    status(&dir, &current)?;
    Ok(current)
}

pub fn confirm(state: &State, task_id: &str) -> Result<()> {
    let busy = state
        .busy
        .lock()
        .map_err(|_| anyhow::anyhow!("任务锁异常"))?;
    if *busy {
        bail!("请等待当前任务结束")
    }
    let pending = rt::read_json(&state.data.join("pending.json"))?;
    if pending["id"] != task_id {
        bail!("确认任务不匹配")
    }
    let dir = job(state, task_id)?;
    let mut current = rt::read_json(&dir.join("status.json"))?;
    if current["result"]["task_complete"] != true || current["result"]["USB_recovered"] != true {
        bail!("需要任务和MSC恢复均核实通过")
    }
    rt::private_json(
        &dir.join("screen-confirmed.json"),
        &json!({"screen_normal":true,"confirmed_by_user":true}),
    )?;
    if current["kind"] == "ssh_start" {
        rt::private_json(&state.data.join("active-ssh.json"), &current["result"])?;
    }
    if current["kind"] == "ssh_stop" {
        fs::remove_file(state.data.join("active-ssh.json"))?;
    }
    current["result"]["screen_confirmation_pending"] = json!(false);
    status(&dir, &current)?;
    fs::remove_file(state.data.join("pending.json"))?;
    Ok(())
}

pub fn reveal(state: &State, task_id: &str, guide: bool) -> Result<()> {
    let dir = job(state, task_id)?;
    let target = if guide {
        PathBuf::from(
            rt::read_json(&dir.join("result.json"))?["guide"]
                .as_str()
                .context("没有生成更新说明")?,
        )
    } else {
        dir
    };
    rt::ordinary(&target, false)?;
    Command::new("/usr/bin/open").arg(target).spawn()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fixed_action_contract() {
        assert!(serde_json::from_value::<Input>(json!({"kind":"backup","command":"rm"})).is_err());
        assert!(validate(&serde_json::from_value(json!({"kind":"shell"})).unwrap()).is_err());
        assert!(id("../../anything").is_err());
    }
    #[test]
    fn screen_cannot_release_failed_task() {
        let t = tempfile::tempdir().unwrap();
        let s = State {
            data: t.path().canonicalize().unwrap(),
            engine: t.path().into(),
            busy: Mutex::new(false),
        };
        let name = "a".repeat(32);
        fs::create_dir_all(s.data.join("tasks").join(&name)).unwrap();
        rt::private_json(&s.data.join("pending.json"), &json!({"id":name})).unwrap();
        status(
            &job(&s, &name).unwrap(),
            &json!({"result":{"task_complete":false,"USB_recovered":true}}),
        )
        .unwrap();
        assert!(confirm(&s, &name).is_err());
        assert!(s.data.join("pending.json").exists());
    }
    #[test]
    fn interrupted_task_keeps_pending_and_imports_later_receipt() {
        let t = tempfile::tempdir().unwrap();
        let s = State {
            data: t.path().canonicalize().unwrap(),
            engine: t.path().into(),
            busy: Mutex::new(false),
        };
        let name = "b".repeat(32);
        let folder = s.data.join("tasks").join(&name);
        fs::create_dir_all(&folder).unwrap();
        rt::private_json(&s.data.join("pending.json"), &json!({"id":name})).unwrap();
        status(
            &folder,
            &json!({"id":name,"kind":"backup","running":true,"created":1}),
        )
        .unwrap();
        let a = overview(&s).unwrap();
        assert_eq!(a["tasks"][0]["interrupted"], true);
        assert!(!a["pending"].is_null());
        rt::private_json(
            &folder.join("privileged-result.json"),
            &json!({"task_complete":false,"device_IO":true,"error":"模拟终态"}),
        )
        .unwrap();
        let b = overview(&s).unwrap();
        assert_eq!(b["tasks"][0]["interrupted"], false);
        assert_eq!(b["tasks"][0]["result"]["error"], "模拟终态");
        assert!(!b["pending"].is_null());
    }
}
