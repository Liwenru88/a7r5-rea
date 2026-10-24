//! 终端只负责管理员认证；固定助手、隔离导出及设备锁仍由原入口执行。
use crate::runtime as rt;
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::{
    fs::{self, OpenOptions},
    io::Write,
    os::unix::{fs::{MetadataExt, OpenOptionsExt}, process::CommandExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

fn now() -> Result<u64> { Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs()) }

fn owned_request(request: &Path) -> Result<PathBuf> {
    rt::ordinary(request, true)?;
    let dir = request.parent().context("授权请求目录无效")?;
    let owner = unsafe { libc::geteuid() };
    let file = fs::metadata(request)?;
    let parent = fs::metadata(dir)?;
    if owner == 0 || file.uid() != owner || parent.uid() != owner
        || file.nlink() != 1 || file.mode() & 0o077 != 0 || parent.mode() & 0o077 != 0 {
        bail!("终端授权请求必须属于当前普通用户，且仅本人可读写")
    }
    let value = rt::read_json(request)?;
    let run = value["run_id"].as_str().context("缺少任务编号")?;
    if !["backup", "update", "ssh_start", "ssh_stop"].contains(&value["kind"].as_str().unwrap_or(""))
        || run.len() != 32 || !run.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) {
        bail!("终端入口只接受固定备份、信任更新或SSH服务请求")
    }
    Ok(dir.to_owned())
}

fn script(exe: &Path, request: &Path) -> Result<String> {
    Ok(format!("#!/bin/bash\numask 077\nexec /usr/bin/env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin TERM=xterm-256color {} --terminal-task {}\n",
        rt::quote(exe.to_str().context("应用路径无效")?),
        rt::quote(request.to_str().context("请求路径无效")?)))
}

fn prepare(exe: &Path, dir: &Path, expires: u64) -> Result<PathBuf> {
    let request = dir.join("request.json");
    owned_request(&request)?;
    rt::private_json(&dir.join("authorization-launch.json"),
        &json!({"schema":1,"request_sha256":rt::hash(&request)?,"expires_at":expires}))?;
    let path = dir.join("管理员授权.command");
    let mut file = OpenOptions::new().create_new(true).write(true).mode(0o700)
        .custom_flags(libc::O_NOFOLLOW).open(&path)?;
    file.write_all(script(exe, &request)?.as_bytes())?;
    file.sync_all()?;
    Ok(path)
}

fn unknown() -> Value {
    json!({"task_complete":false,"can_replug":false,"awaiting_helper_receipt":true,
        "error":"终端授权或助手未返回完整结果；保留连接与记录，不自动重试。后续设备回执到达时会自动载入。"})
}

fn receipt(dir: &Path) -> Result<Option<Value>> {
    let result = dir.join("privileged-result.json");
    if result.exists() { return Ok(Some(rt::read_json(&result)?)) }
    let finished = dir.join("authorization-finished.json");
    if finished.exists() {
        let value = rt::read_json(&finished)?;
        return Ok(Some(if value["sudo_started"] == false {
            json!({"task_complete":false,"device_IO":false,"can_replug":true,
                "error":value["error"].as_str().unwrap_or("终端授权未开始，未执行设备操作")})
        } else { unknown() }));
    }
    Ok(None)
}

fn poll(dir: &Path, expired: bool) -> Result<Option<Value>> {
    if let Some(value) = receipt(dir)? { return Ok(Some(value)) }
    let started = dir.join("authorization-started.json").exists();
    if started || expired {
        if let Some(_guard) = rt::try_lock(&dir.join("authorization.lock"))? {
            if let Some(value) = receipt(dir)? { return Ok(Some(value)) }
            if dir.join("authorization-started.json").exists() { return Ok(Some(unknown())) }
            // 与终端监督进程共享同一把锁，阻止超时窗口稍后再执行旧请求。
            rt::private_json(&dir.join("authorization-cancelled.json"), &json!({"not_started":true}))?;
            return Ok(Some(json!({"task_complete":false,"device_IO":false,"can_replug":true,
                "error":"终端未及时启动授权，此请求已取消；未执行设备操作"})));
        }
    }
    Ok(None)
}

pub fn launch(exe: &Path, dir: &Path) -> Result<Value> {
    let expires = now()? + 120;
    let path = prepare(exe, dir, expires)?;
    let output = Command::new("/usr/bin/open").env_clear()
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        .args(["-a", "/System/Applications/Utilities/Terminal.app"]).arg(path)
        .stdin(Stdio::null()).output()?;
    if !output.status.success() {
        rt::private_json(&dir.join("authorization-open-error.json"),
            &json!({"error":String::from_utf8_lossy(&output.stderr)}))?;
        // 即使open失败，也通过取消令牌封住可能迟到的终端启动。
        if let Some(value) = poll(dir, true)? { return Ok(value) }
    }
    loop {
        if let Some(value) = poll(dir, now()? >= expires)? { return Ok(value) }
        std::thread::sleep(Duration::from_millis(250));
    }
}

fn supervise(request: &Path, make_command: impl FnOnce() -> Command) -> Result<()> {
    let dir = owned_request(request)?;
    let _guard = rt::lock(&dir.join("authorization.lock"))?;
    if dir.join("authorization-started.json").exists() {
        bail!("此授权已有执行尝试，保留原回执，不再启动")
    }
    let mut sudo_started = false;
    let outcome = (|| -> Result<std::process::ExitStatus> {
        let launch = rt::read_json(&dir.join("authorization-launch.json"))?;
        if dir.join("authorization-cancelled.json").exists()
            || now()? >= launch["expires_at"].as_u64().context("授权有效期无效")?
            || rt::hash(request)? != launch["request_sha256"].as_str().context("请求摘要缺失")? {
            bail!("授权请求已取消、过期或发生变化；未启动设备操作")
        }
        rt::private_json(&dir.join("authorization-started.json"), &json!({"pid":std::process::id()}))?;
        let mut child = make_command().spawn()?;
        sudo_started = true;
        Ok(child.wait()?)
    })();
    let finished = match outcome {
        Ok(status) => json!({"sudo_started":sudo_started,"exit_code":status.code(),"success":status.success()}),
        Err(error) => json!({"sudo_started":sudo_started,"error":error.to_string()}),
    };
    rt::publish_json(&dir.join("authorization-finished.json"), &finished)?;
    Ok(())
}

pub fn terminal_task(request: &Path) -> Result<()> {
    let exe = std::env::current_exe()?;
    println!("请在此输入这台Mac的登录密码；它不是相机SSH密码。执行开始后请保持相机连接和供电。\n密码不会保存到任务记录；请等待客户端显示结果。");
    // 只改变此独立CLI监督进程；终端关闭后仍等待回执，Ctrl+C交由sudo处理。
    unsafe {
        libc::signal(libc::SIGHUP, libc::SIG_IGN);
        libc::signal(libc::SIGINT, libc::SIG_IGN);
        libc::signal(libc::SIGTERM, libc::SIG_IGN);
    }
    supervise(request, || {
        let mut command = Command::new("/usr/bin/sudo");
        command.args(["--"]).arg(exe).arg("--privileged-task").arg(request);
        unsafe { command.pre_exec(|| {
            libc::signal(libc::SIGINT, libc::SIG_DFL);
            libc::signal(libc::SIGTERM, libc::SIG_DFL);
            Ok(())
        }); }
        command
    })?;
    println!("本次授权进程已结束，请回客户端查看结果；此窗口可以关闭。");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::os::unix::fs::PermissionsExt;
    fn fixture() -> (tempfile::TempDir, PathBuf) {
        let temp = tempfile::tempdir().unwrap();
        let dir = temp.path().canonicalize().unwrap();
        fs::set_permissions(&dir, fs::Permissions::from_mode(0o700)).unwrap();
        rt::private_json(&dir.join("request.json"), &json!({"run_id":"a".repeat(32),"kind":"backup"})).unwrap();
        (temp, dir)
    }

    #[test]
    fn launch_script_quotes_paths_and_does_not_store_credentials() {
        let (_temp, dir) = fixture();
        let exe = dir.join("应用 ' $(touch injected).app/executable");
        let path = prepare(&exe, &dir, now().unwrap()+120).unwrap();
        assert_eq!(fs::metadata(&path).unwrap().mode() & 0o777, 0o700);
        let source = fs::read_to_string(&path).unwrap();
        assert!(source.contains("--terminal-task"));
        assert!(!source.contains("sudo -S") && !source.contains("password"));
        assert!(Command::new("/bin/bash").args(["-n"]).arg(&path).status().unwrap().success());
        // 实际执行含引号和命令替换字符的路径，验证它只作为文件名，不作为shell指令。
        fs::create_dir_all(exe.parent().unwrap()).unwrap();
        fs::write(&exe, "#!/bin/bash\nexit 0\n").unwrap();
        fs::set_permissions(&exe, fs::Permissions::from_mode(0o700)).unwrap();
        assert!(Command::new("/bin/bash").arg(path).current_dir(&dir).status().unwrap().success());
        assert!(!dir.join("injected").exists());
    }

    #[test]
    fn terminal_completion_and_cancellation_return_without_retry() {
        for code in [0, 1, 130] {
            let (_temp, dir) = fixture();
            prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
            supervise(&dir.join("request.json"), || {
                let mut c = Command::new("/bin/bash"); c.args(["-c", &format!("exit {code}")]); c
            }).unwrap();
            assert_eq!(rt::read_json(&dir.join("authorization-finished.json")).unwrap()["exit_code"], code);
            assert_eq!(poll(&dir, false).unwrap().unwrap()["awaiting_helper_receipt"], true);
        }
    }

    #[test]
    fn helper_receipt_preserves_success_and_original_failure() {
        for complete in [true, false] {
            let (_temp, dir) = fixture();
            prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
            let expected = json!({"task_complete":complete,"simulation":true,"device_IO":false,
                "error":if complete { Value::Null } else { json!("固定助手的原始错误") }});
            let shell = format!("/usr/bin/printf %s {} > {}", rt::quote(&expected.to_string()),
                rt::quote(dir.join("privileged-result.json").to_str().unwrap()));
            supervise(&dir.join("request.json"), || {
                let mut c = Command::new("/bin/bash"); c.args(["-c", &shell]); c
            }).unwrap();
            assert_eq!(poll(&dir, false).unwrap().unwrap(), expected);
        }
    }

    #[test]
    fn timeout_cancellation_blocks_late_terminal_execution() {
        let (_temp, dir) = fixture();
        prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
        assert_eq!(poll(&dir, true).unwrap().unwrap()["device_IO"], false);
        supervise(&dir.join("request.json"), || panic!("取消后不得启动任何进程")).unwrap();
        assert_eq!(poll(&dir, false).unwrap().unwrap()["device_IO"], false);
    }

    #[test]
    fn active_authorization_is_not_cancelled_by_launch_timeout() {
        let (_temp, dir) = fixture();
        prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
        let guard = rt::lock(&dir.join("authorization.lock")).unwrap();
        rt::private_json(&dir.join("authorization-started.json"), &json!({"pid":1})).unwrap();
        assert!(poll(&dir, true).unwrap().is_none());
        assert!(!dir.join("authorization-cancelled.json").exists());
        drop(guard);
        assert_eq!(poll(&dir, true).unwrap().unwrap()["awaiting_helper_receipt"], true);
        rt::publish_json(&dir.join("privileged-result.json"), &json!({"task_complete":false,"error":"原设备错误"})).unwrap();
        assert_eq!(poll(&dir, false).unwrap().unwrap()["error"], "原设备错误");
    }

    #[test]
    fn changed_request_and_duplicate_start_never_execute_again() {
        let (_temp, dir) = fixture();
        prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
        fs::write(dir.join("request.json"), br#"{"kind":"update","run_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#).unwrap();
        supervise(&dir.join("request.json"), || panic!("摘要变化后不得执行")).unwrap();
        assert_eq!(poll(&dir, false).unwrap().unwrap()["device_IO"], false);
        let (_other, dir) = fixture();
        prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
        rt::private_json(&dir.join("authorization-started.json"), &json!({"pid":1})).unwrap();
        assert!(supervise(&dir.join("request.json"), || panic!("已有尝试不得重复执行")).is_err());
        assert_eq!(poll(&dir, false).unwrap().unwrap()["awaiting_helper_receipt"], true);
    }

    #[test]
    fn ssh_terminal_requests_preserve_private_receipts_without_retry() {
        for kind in ["ssh_start", "ssh_stop"] {
            for code in [0, 1, 130] {
                let (_temp, dir) = fixture();
                let request = json!({"run_id":"a".repeat(32),"kind":kind,
                    "password_hash":"fixture-ssh-hash","active":{"run_id":"previous-instance"}});
                fs::write(dir.join("request.json"), request.to_string()).unwrap();
                let path = prepare(Path::new("/unused"), &dir, now().unwrap()+120).unwrap();
                let source = fs::read_to_string(path).unwrap();
                assert!(!source.contains("fixture-ssh-hash") && !source.contains("previous-instance"));
                let result = json!({"kind":kind,"task_complete":true,"device_IO":false,"simulation":true});
                supervise(&dir.join("request.json"), || {
                    if code == 0 { rt::publish_json(&dir.join("privileged-result.json"), &result).unwrap(); }
                    let mut c = Command::new("/bin/bash"); c.args(["-c", &format!("exit {code}")]); c
                }).unwrap();
                let received = poll(&dir, false).unwrap().unwrap();
                if code == 0 { assert_eq!(received, result); }
                else { assert_eq!(received["awaiting_helper_receipt"], true); }
                assert!(supervise(&dir.join("request.json"), || panic!("不重复启动SSH事务")).is_err());
            }
        }
    }

    #[test]
    fn unapproved_action_expired_launch_and_public_request_are_rejected() {
        let (_temp, dir) = fixture();
        fs::write(dir.join("request.json"), br#"{"kind":"shell","run_id":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}"#).unwrap();
        assert!(prepare(Path::new("/unused"), &dir, now().unwrap()+120).is_err());
        let (_temp, dir) = fixture();
        prepare(Path::new("/unused"), &dir, 0).unwrap();
        supervise(&dir.join("request.json"), || panic!("过期授权不得执行")).unwrap();
        assert_eq!(poll(&dir, false).unwrap().unwrap()["device_IO"], false);
        let (_temp, dir) = fixture();
        fs::set_permissions(dir.join("request.json"), fs::Permissions::from_mode(0o644)).unwrap();
        assert!(prepare(Path::new("/unused"), &dir, now().unwrap()+120).is_err());
    }
}
