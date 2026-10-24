use crate::runtime as rt;
use anyhow::{bail, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use std::{
    fs,
    os::unix::fs::{DirBuilderExt, PermissionsExt},
    path::{Path, PathBuf},
    process::Command,
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
    #[serde(default)]
    force_install: bool,
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

fn pre_service_failure(value: &Value) -> bool {
    let report = &value["report"];
    value["task_complete"] == false
        && value["device_IO"] == true
        && report["failure"].as_str().is_some_and(|s| !s.is_empty())
        && ["service_start_requested", "first_authentication_passed", "second_authentication_passed",
            "communication_verified", "camera_file_write_commands_sent", "debug_commands_sent",
            "preload_written", "card_formatted"]
            .iter().all(|key| report[*key] == false)
        && report["files"].as_array().is_some_and(|files| files.is_empty())
        && report["service_stop_attempts"].as_u64() == Some(0)
        && ["camera_protocol_requests", "fixed_writes_attempted", "trigger_attempts"].iter()
            .all(|key| report.get(*key).is_none_or(|count| count.as_u64() == Some(0)))
}

fn recovery_available(value: &Value) -> bool {
    value["task_complete"] == true || pre_service_failure(value)
}

fn failed_recovery_proven(value: &Value) -> bool {
    let proof = &value["host_recovery"];
    let baseline = value.get("recovery_baseline").unwrap_or(&value["baseline"]);
    proof["recovered"] == true && proof["camera_protocol_requests"].as_u64() == Some(0)
        && baseline["kind"] == "ordinary" && baseline["model"] == "ILCE-7RM5"
        && baseline["location_id"].as_u64().is_some()
        && baseline["media"].as_array().is_some_and(|rows| !rows.is_empty())
        && baseline["drivers"].as_array().is_some_and(|rows| !rows.is_empty())
        && proof["observations"].as_array().is_some_and(|rows| rows.len() >= 2
            && rows.iter().rev().take(2).all(|row|
                ["kind", "model", "location_id", "media", "drivers"].iter()
                    .all(|key| row[*key] == baseline[*key])))
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
                    let plain = rt::read_json(&plain)?;
                    if plain["awaiting_helper_receipt"] == true { None } else { Some(plain) }
                } else {
                    None
                };
                value["running"] = json!(false);
                value["interrupted"] = json!(result.is_none());
                value["result"]=result.unwrap_or_else(|| value.get("result").cloned().unwrap_or_else(||json!({"task_complete":false,"can_replug":false,"error":"应用曾中断，结果尚未取得。保留连接与待恢复记录，不自动重试；后续回执到达时会自动载入。"})));
                crate::backup_output::finish(&directory, &mut value["result"]);
                // 终端的迟到回执也要登记服务实例，不能只更新任务卡片。
                if let Err(error) = record_service_result(state, &directory,
                    value["kind"].as_str().unwrap_or(""), &value["result"]) {
                    value["result"]["service_tracking_error"] = json!(error.to_string());
                    value["interrupted"] = json!(true);
                }
                status(&directory, &value)?;
            }
            // 仅返回恢复能力，不追写或升级旧任务的失败证据。
            value["recovery_available"] = json!(recovery_available(&value["result"]));
            tasks.push(value);
        }
    }
    tasks.sort_by_key(|v| std::cmp::Reverse(v["created"].as_u64().unwrap_or(0)));
    tasks.truncate(25);
    Ok(json!({"busy":*busy,
        "pending":Value::Null,"legacy_pending_record":pending.exists(),
        "active_ssh":active.exists(),"tasks":tasks,"data":state.data,"test_package":true}))
}

fn validate(input: &Input) -> Result<()> {
    if input.force_install && input.kind != "update" {
        bail!("强制模式仅用于信任安装")
    }
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
    if input.kind == "update" && !input.force_install {
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
    if input.kind == "backup" {
        if let Some(directory)=&input.output { crate::backup_output::validate(Path::new(directory))?; }
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
    // SSH记录用于管理原实例，不阻止按当前MSC连接执行维护任务。
    if input.kind == "ssh_start" && state.data.join("active-ssh.json").exists() {
        bail!("请先停止当前SSH实例并确认相机恢复")
    }
    rt::verify(&state.engine)?;
    let run_id = uuid::Uuid::new_v4().simple().to_string();
    let dir = job(&state, &run_id)?;
    fs::DirBuilder::new().mode(0o700).create(&dir)?;
    if input.kind=="backup" {
        if let Some(directory)=&input.output {
            crate::backup_output::prepare(&dir,Path::new(directory),&run_id)?;
        }
    }
    let mut request = json!({"kind":input.kind,"run_id":run_id});
    if input.kind == "firmware" {
        request["source"] = json!(input.source);
        request["output"] = json!(input.output);
        request["features"] = json!(input.features);
        request["version"] = json!(input.version);
    }
    if input.kind == "update" {
        request["backup_manifest"] = json!(input.backup_manifest);
        request["force_install"] = json!(input.force_install);
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
    let initial = json!({"id":run_id,"kind":input.kind,"created":created,"running":true,"message":if device{"请在打开的终端中输入这台Mac的登录密码（不是相机SSH密码）；完成后结果自动返回此处"}else{"正在验证并封装固件，可能需要几分钟"},"directory":dir});
    status(&dir, &initial)?;
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
            crate::authorization::launch(&exe, &dir)
        })();
        let mut result = outcome.unwrap_or_else(
            |e| json!({"error":e.to_string(),"task_complete":false,"can_replug":false,"awaiting_helper_receipt":device}),
        );
        // 所选目录只由当前普通用户写入，不传给管理员设备助手。
        crate::backup_output::finish(&dir, &mut result);
        if device {
            if let Err(error) = record_service_result(&thread_state, &dir, &input.kind, &result) {
                result["service_tracking_error"] = json!(error.to_string());
            }
        }
        let finished = json!({"id":thread_id,"kind":input.kind,"created":created,"running":false,"interrupted":result["awaiting_helper_receipt"]==true,"result":result,"directory":dir});
        let _ = rt::private_json(&dir.join("result.json"), &result);
        let _ = status(&dir, &finished);
        if device && result["device_IO"] == false {
            let _ = rt::private_json(
                &dir.join("no-device-operation.json"),
                &json!({"confirmed":true}),
            );
        }
        if let Ok(mut busy) = thread_state.busy.lock() {
            *busy = false;
        }
    });
    Ok(run_id)
}

fn record_service_result(state: &State, dir: &Path, kind: &str, result: &Value) -> Result<()> {
    if result["task_complete"] != true {
        return Ok(())
    }
    let active = state.data.join("active-ssh.json");
    if kind == "ssh_start" {
        // 活动实例独立于屏幕确认登记，后续操作不会遗漏已经启动的服务。
        if active.exists() {
            if rt::read_json(&active)? == *result { return Ok(()) }
            bail!("已有其他SSH活动记录，保留两份回执，不覆盖")
        }
        rt::private_json(&active, result)?;
    } else if kind == "ssh_stop" {
        let ended = dir.join("ended-ssh.json");
        if ended.exists() {
            let previous = rt::read_json(&ended)?;
            if previous["run_id"].as_str().is_none() || previous["run_id"] != result["run_id"] {
                bail!("已有停止归档与回执不匹配")
            }
            // 中断恢复可重复载入回执，但不能删除后来启动的新实例。
            if active.exists() && rt::read_json(&active)?["run_id"] == result["run_id"] {
                fs::remove_file(&active)?;
            }
            return Ok(())
        }
        let previous = rt::read_json(&active)?;
        if previous["run_id"].as_str().is_none() || previous["run_id"] != result["run_id"] {
            bail!("停止回执与活动SSH实例不匹配")
        }
        rt::private_json(&ended, &previous)?;
        fs::remove_file(&active)?;
    }
    Ok(())
}

pub fn recover(state: &State, task_id: &str) -> Result<Value> {
    let _busy = state
        .busy
        .lock()
        .map_err(|_| anyhow::anyhow!("任务锁异常"))?;
    if *_busy {
        bail!("请等待当前任务结束")
    }
    let dir = job(state, task_id)?;
    let mut current = rt::read_json(&dir.join("status.json"))?;
    let result = &current["result"];
    if !recovery_available(result) {
        bail!("服务已启动或阶段证据不全，请保持连接并查看失败记录")
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
    let dir = job(state, task_id)?;
    let mut current = rt::read_json(&dir.join("status.json"))?;
    let completed = current["result"]["task_complete"] == true;
    if current["result"]["USB_recovered"] != true
        || (!completed && !(pre_service_failure(&current["result"]) && failed_recovery_proven(&current["result"]))) {
        bail!("需要任务完成或明确未启动服务，并核实MSC稳定恢复")
    }
    let screen_path = dir.join("screen-confirmed.json");
    let screen = json!({"screen_normal":true,"confirmed_by_user":true,"task_complete":completed});
    if screen_path.exists() {
        if rt::read_json(&screen_path)? != screen {
            bail!("已有屏幕确认记录不匹配，保留现场")
        }
    } else {
        rt::private_json(&screen_path, &screen)?;
    }
    current["result"]["screen_confirmation_pending"] = json!(false);
    if !completed {
        current["result"]["recovery_resolved"] = json!(true);
    }
    status(&dir, &current)?;
    // 确认只补充本任务回执；不消费或清除旧全局标记，不改变其他SSH实例。
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

pub fn reveal_backup(state: &State, task_id: &str) -> Result<()> {
    let dir=job(state,task_id)?;
    let value=rt::read_json(&dir.join("status.json"))?;
    let result=&value["result"];
    let target=if let Some(path)=result["backup_export_directory"].as_str() { PathBuf::from(path) }
        else { Path::new(result["backup_file"].as_str().context("没有完整备份")?).parent().context("备份目录无效")?.to_path_buf() };
    rt::ordinary(&target,false)?;
    Command::new("/usr/bin/open").arg(target).spawn()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn force_install_is_explicit_and_bound_to_update() {
        let force: Input = serde_json::from_value(json!({"kind":"update","force_install":true})).unwrap();
        assert!(validate(&force).is_ok());
        let ordinary: Input = serde_json::from_value(json!({"kind":"update"})).unwrap();
        assert!(validate(&ordinary).is_err());
        let wrong: Input = serde_json::from_value(json!({"kind":"backup","force_install":true})).unwrap();
        assert!(validate(&wrong).is_err());
        assert!(serde_json::from_value::<Input>(json!({"kind":"update","force_install":"true"})).is_err());
    }

    fn failed_state(folder: &Path, mut result: Value) -> (State, String) {
        let s = State {
            data: folder.canonicalize().unwrap(),
            engine: folder.into(),
            busy: Mutex::new(false),
        };
        let name = "c".repeat(32);
        fs::create_dir_all(s.data.join("tasks").join(&name)).unwrap();
        rt::private_json(&s.data.join("pending.json"), &json!({"id":name,"kind":result["kind"]})).unwrap();
        let baseline = result["baseline"].clone();
        result["USB_recovered"] = json!(true);
        result["host_recovery"] = json!({"recovered":true,"camera_protocol_requests":0,"observations":[baseline,baseline]});
        let kind = result["kind"].clone();
        status(&job(&s, &name).unwrap(), &json!({"id":name,"kind":kind,"running":false,"result":result})).unwrap();
        (s, name)
    }

    #[test]
    fn pre_service_recovery_contract_preserves_failure_and_pending_receipt() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        for case in contract["cases"].as_array().unwrap() {
            let t = tempfile::tempdir().unwrap();
            let mut result = contract["base"].clone();
            for (key, value) in case["patch"].as_object().unwrap() {
                result["report"][key] = value.clone();
            }
            if let Some(key) = case["remove"].as_str() {
                result["report"].as_object_mut().unwrap().remove(key);
            }
            let (s, name) = failed_state(t.path(), result);
            let original_pending = fs::read(s.data.join("pending.json")).unwrap();
            let accepted = confirm(&s, &name).is_ok();
            assert_eq!(accepted, case["allowed"].as_bool().unwrap(), "{}", case["name"]);
            let dir = job(&s, &name).unwrap();
            if accepted {
                assert_eq!(fs::read(s.data.join("pending.json")).unwrap(), original_pending);
                let value = rt::read_json(&dir.join("status.json")).unwrap();
                assert_eq!(value["result"]["task_complete"], false);
                assert_eq!(value["result"]["recovery_resolved"], true);
                assert_eq!(value["result"]["error"], contract["base"]["error"]);
            } else {
                assert_eq!(fs::read(s.data.join("pending.json")).unwrap(), original_pending);
            }
        }
    }

    #[test]
    fn failed_ssh_recovery_keeps_active_instance_and_requires_host_proof() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let t = tempfile::tempdir().unwrap();
        let mut result = contract["base"].clone();
        result["kind"] = json!("ssh_stop");
        let (s, name) = failed_state(t.path(), result);
        rt::private_json(&s.data.join("active-ssh.json"), &json!({"run_id":"old-instance"})).unwrap();
        let active = fs::read(s.data.join("active-ssh.json")).unwrap();
        let dir = job(&s, &name).unwrap();
        let mut value = rt::read_json(&dir.join("status.json")).unwrap();
        let proof = value["result"]["host_recovery"].take();
        let mut wrong_port = proof.clone();
        wrong_port["observations"][1]["location_id"] = json!(1);
        let mut one_observation = proof.clone();
        one_observation["observations"].as_array_mut().unwrap().pop();
        let mut protocol_request = proof.clone();
        protocol_request["camera_protocol_requests"] = json!(1);
        for invalid in [Value::Null, wrong_port, one_observation, protocol_request] {
            value["result"]["host_recovery"] = invalid;
            status(&dir, &value).unwrap();
            assert!(confirm(&s, &name).is_err());
            assert!(s.data.join("pending.json").exists());
            assert!(!dir.join("screen-confirmed.json").exists());
        }
        value["result"]["host_recovery"] = proof;
        status(&dir, &value).unwrap();
        assert!(confirm(&s, &name).is_ok());
        assert_eq!(fs::read(s.data.join("active-ssh.json")).unwrap(), active);
    }

    #[test]
    fn overview_exposes_legacy_recovery_without_rewriting_records() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let t = tempfile::tempdir().unwrap();
        let (s, name) = failed_state(t.path(), contract["base"].clone());
        let path = job(&s, &name).unwrap().join("status.json");
        let before = fs::read(&path).unwrap();
        assert_eq!(overview(&s).unwrap()["tasks"][0]["recovery_available"], true);
        assert_eq!(fs::read(&path).unwrap(), before);
        assert!(s.data.join("pending.json").exists());
    }

    #[test]
    fn interrupted_failure_confirmation_can_finish_without_overwriting_receipts() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let t = tempfile::tempdir().unwrap();
        let (s, name) = failed_state(t.path(), contract["base"].clone());
        let dir = job(&s, &name).unwrap();
        rt::private_json(&dir.join("screen-confirmed.json"), &json!({"screen_normal":true,"confirmed_by_user":true,"task_complete":false})).unwrap();
        fs::hard_link(s.data.join("pending.json"), dir.join("pending-resolved.json")).unwrap();
        let archived = fs::read(dir.join("pending-resolved.json")).unwrap();
        assert!(confirm(&s, &name).is_ok());
        assert!(s.data.join("pending.json").exists());
        assert_eq!(fs::read(dir.join("pending-resolved.json")).unwrap(), archived);
    }

    #[test]
    fn fixed_action_contract() {
        assert!(serde_json::from_value::<Input>(json!({"kind":"backup","command":"rm"})).is_err());
        assert!(validate(&serde_json::from_value(json!({"kind":"shell"})).unwrap()).is_err());
        assert!(id("../../anything").is_err());
    }

    #[test]
    fn old_pending_does_not_block_start_or_get_removed() {
        let t = tempfile::tempdir().unwrap();
        let s = State { data: t.path().canonicalize().unwrap(), engine: t.path().into(), busy: Mutex::new(false) };
        rt::private_json(&s.data.join("pending.json"), &json!({"id":"legacy"})).unwrap();
        let old = fs::read(s.data.join("pending.json")).unwrap();
        // 空引擎必在材料验证阶段退出，测试不会启动授权助手或设备事务。
        let error = start(Arc::new(s), serde_json::from_value(json!({"kind":"backup"})).unwrap()).unwrap_err();
        assert!(!error.to_string().contains("上次设备任务"));
        assert_eq!(fs::read(t.path().join("pending.json")).unwrap(), old);
    }

    #[test]
    fn ssh_tracking_does_not_block_maintenance_or_get_removed() {
        for kind in ["backup","update","force"] {
            let t=tempfile::tempdir().unwrap();
            let path=t.path().canonicalize().unwrap();
            let s=Arc::new(State {data:path.clone(),engine:path,busy:Mutex::new(false)});
            let active=s.data.join("active-ssh.json");
            rt::private_json(&active,&json!({"run_id":"existing-instance"})).unwrap();
            let old=fs::read(&active).unwrap();
            let backup=s.data.join("backup.json");rt::private_json(&backup,&json!({})).unwrap();
            let input=match kind {
                "update"=>json!({"kind":"update","backup_manifest":backup}),
                "force"=>json!({"kind":"update","force_install":true}),
                _=>json!({"kind":"backup"}),
            };
            *s.busy.lock().unwrap()=true;
            let error=start(s.clone(),serde_json::from_value(input.clone()).unwrap()).unwrap_err();
            assert_eq!(error.to_string(),"已有任务正在执行");
            *s.busy.lock().unwrap()=false;
            // 空引擎应在材料验证阶段退出，不启动助手或真实设备事务。
            let expected=rt::verify(&s.engine).unwrap_err().to_string();
            let error=start(s,serde_json::from_value(input).unwrap()).unwrap_err();
            assert_eq!(error.to_string(),expected);
            assert_eq!(fs::read(&active).unwrap(),old);
            assert!(!t.path().join("tasks").exists());
        }
    }

    #[test]
    fn optional_confirmation_accepts_fresh_baseline_and_preserves_old_port() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let t = tempfile::tempdir().unwrap();
        let (s, name) = failed_state(t.path(), contract["base"].clone());
        let dir = job(&s, &name).unwrap();
        let mut value = rt::read_json(&dir.join("status.json")).unwrap();
        let old = value["result"]["baseline"].clone();
        let mut current = old.clone();
        current["location_id"] = json!(0x14100000);
        value["result"]["recovery_baseline"] = current.clone();
        value["result"]["host_recovery"]["observations"] = json!([current,current]);
        status(&dir, &value).unwrap();
        assert!(confirm(&s, &name).is_ok());
        assert_eq!(rt::read_json(&dir.join("status.json")).unwrap()["result"]["baseline"], old);
        assert!(s.data.join("pending.json").exists());
    }

    #[test]
    fn ssh_tracking_is_independent_of_screen_and_preserves_ended_record() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let t = tempfile::tempdir().unwrap();
        let (s, name) = failed_state(t.path(), contract["base"].clone());
        let dir = job(&s, &name).unwrap();
        let started = json!({"run_id":"instance-a","task_complete":true,"USB_recovered":false,"host_public_key":"verified-key"});
        record_service_result(&s, &dir, "ssh_start", &started).unwrap();
        record_service_result(&s, &dir, "ssh_start", &started).unwrap();
        assert_eq!(rt::read_json(&s.data.join("active-ssh.json")).unwrap(), started);
        assert!(!dir.join("screen-confirmed.json").exists());
        record_service_result(&s, &dir, "ssh_stop", &json!({"task_complete":false})).unwrap();
        assert!(record_service_result(&s, &dir, "ssh_stop", &json!({"task_complete":true,"run_id":"other-instance"})).is_err());
        assert!(s.data.join("active-ssh.json").exists());
        record_service_result(&s, &dir, "ssh_stop", &json!({"task_complete":true,"run_id":"instance-a"})).unwrap();
        assert!(!s.data.join("active-ssh.json").exists());
        assert_eq!(rt::read_json(&dir.join("ended-ssh.json")).unwrap(), started);
        let newer = json!({"run_id":"new-instance","task_complete":true});
        rt::private_json(&s.data.join("active-ssh.json"), &newer).unwrap();
        record_service_result(&s, &dir, "ssh_stop", &json!({"task_complete":true,"run_id":"instance-a"})).unwrap();
        assert_eq!(rt::read_json(&s.data.join("active-ssh.json")).unwrap(), newer);
        assert!(s.data.join("pending.json").exists());
    }

    #[test]
    fn late_ssh_receipts_update_tracking_and_preserve_original_unknown_result() {
        for kind in ["ssh_start", "ssh_stop"] {
            for complete in [false, true] {
                let t = tempfile::tempdir().unwrap();
                let s = State { data:t.path().canonicalize().unwrap(), engine:t.path().into(), busy:Mutex::new(false) };
                let name = "d".repeat(32);
                let dir = job(&s, &name).unwrap();
                fs::create_dir_all(&dir).unwrap();
                let unknown = json!({"task_complete":false,"awaiting_helper_receipt":true,"error":"授权结果未知"});
                rt::private_json(&dir.join("result.json"), &unknown).unwrap();
                status(&dir, &json!({"id":name,"kind":kind,"running":false,"interrupted":true,"result":unknown})).unwrap();
                let started = json!({"run_id":"instance-a","task_complete":true,"host_public_key":"verified-key"});
                if kind == "ssh_stop" { rt::private_json(&s.data.join("active-ssh.json"), &started).unwrap(); }
                let before = overview(&s).unwrap();
                assert_eq!(before["tasks"][0]["interrupted"], true);
                let receipt = if kind == "ssh_start" && complete { started.clone() }
                    else { json!({"run_id":"instance-a","task_complete":complete}) };
                rt::publish_json(&dir.join("privileged-result.json"), &receipt).unwrap();
                let received = overview(&s).unwrap();
                assert_eq!(received["tasks"][0]["interrupted"], false);
                assert_eq!(received["tasks"][0]["result"], receipt);
                assert_eq!(received["active_ssh"], if kind == "ssh_start" { complete } else { !complete });
                if kind == "ssh_stop" && complete {
                    assert_eq!(rt::read_json(&dir.join("ended-ssh.json")).unwrap(), started);
                }
                assert_eq!(rt::read_json(&dir.join("result.json")).unwrap(), unknown);
                assert_eq!(overview(&s).unwrap()["active_ssh"], received["active_ssh"]);
            }
        }
    }

    #[test]
    fn confirming_old_stop_never_removes_new_ssh_instance() {
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let t = tempfile::tempdir().unwrap();
        let mut result = contract["base"].clone();
        result["kind"] = json!("ssh_stop");
        result["task_complete"] = json!(true);
        let (s, name) = failed_state(t.path(), result);
        let active = json!({"run_id":"new-instance"});
        rt::private_json(&s.data.join("active-ssh.json"), &active).unwrap();
        confirm(&s, &name).unwrap();
        assert_eq!(rt::read_json(&s.data.join("active-ssh.json")).unwrap(), active);
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
        assert_eq!(a["legacy_pending_record"], true);
        rt::private_json(
            &folder.join("privileged-result.json"),
            &json!({"task_complete":false,"device_IO":true,"error":"模拟终态"}),
        )
        .unwrap();
        let b = overview(&s).unwrap();
        assert_eq!(b["tasks"][0]["interrupted"], false);
        assert_eq!(b["tasks"][0]["result"]["error"], "模拟终态");
        assert_eq!(b["legacy_pending_record"], true);
    }

    #[test]
    fn unknown_authorization_keeps_waiting_for_helper_despite_plain_failure_record() {
        let t = tempfile::tempdir().unwrap();
        let contract: Value = serde_json::from_str(include_str!("../../tests/fixtures/pre-service-recovery.json")).unwrap();
        let (s, name) = failed_state(t.path(), contract["base"].clone());
        let folder = job(&s, &name).unwrap();
        let unknown = json!({"task_complete":false,"awaiting_helper_receipt":true,"error":"授权结果未知"});
        rt::private_json(&folder.join("result.json"), &unknown).unwrap();
        status(&folder, &json!({"id":name,"running":false,"interrupted":true,"result":unknown})).unwrap();
        assert_eq!(overview(&s).unwrap()["tasks"][0]["interrupted"], true);
        rt::private_json(&folder.join("privileged-result.json"), &json!({"task_complete":false,"error":"迟到的原始设备错误"})).unwrap();
        let later = overview(&s).unwrap();
        assert_eq!(later["tasks"][0]["interrupted"], false);
        assert_eq!(later["tasks"][0]["result"]["error"], "迟到的原始设备错误");
        assert_eq!(rt::read_json(&folder.join("result.json")).unwrap(), unknown);
    }
}
