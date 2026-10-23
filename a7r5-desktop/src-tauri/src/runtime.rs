use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    os::unix::fs::{MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Component, Path, PathBuf},
    process::Command,
};

pub fn engine() -> Result<PathBuf> {
    let exe = std::env::current_exe()?;
    let contents = exe
        .parent()
        .and_then(Path::parent)
        .context("应用目录不完整")?;
    if contents.file_name().and_then(|p| p.to_str()) != Some("Contents") {
        bail!("请从完整.app测试包运行")
    }
    Ok(contents.join("Resources/engine"))
}

pub fn ordinary(path: &Path, file: bool) -> Result<()> {
    if !path.is_absolute()
        || path.starts_with("/dev")
        || path.components().any(|c| matches!(c, Component::ParentDir))
    {
        bail!("路径无效")
    }
    for p in path.ancestors() {
        if p.exists() && fs::symlink_metadata(p)?.file_type().is_symlink() {
            bail!("不接受符号链接路径")
        }
    }
    if file && !fs::symlink_metadata(path)?.is_file() {
        bail!("需要普通文件")
    }
    Ok(())
}

pub fn hash(path: &Path) -> Result<String> {
    let mut f = File::open(path)?;
    let mut h = Sha256::new();
    let mut buf = [0u8; 65536];
    loop {
        let n = f.read(&mut buf)?;
        if n == 0 {
            break;
        }
        h.update(&buf[..n]);
    }
    Ok(format!("{:x}", h.finalize()))
}

pub fn verify(root: &Path) -> Result<Value> {
    ordinary(root, false)?;
    let manifest = root.join("integrity.json");
    ordinary(&manifest, true)?;
    if hash(&manifest)? != include_str!("../engine.sha256").trim() {
        bail!("运行材料清单变化，请重新获取完整测试包")
    }
    let data: Value = serde_json::from_slice(&fs::read(manifest)?)?;
    for (name, row) in data["files"].as_object().context("材料清单格式无效")? {
        let relative = Path::new(name);
        if relative.is_absolute()
            || relative
                .components()
                .any(|p| !matches!(p, Component::Normal(_)))
        {
            bail!("材料路径无效")
        }
        let path = root.join(relative);
        ordinary(&path, true)?;
        if fs::metadata(&path)?.len() != row["bytes"].as_u64().context("材料大小无效")?
            || hash(&path)? != row["sha256"].as_str().context("材料摘要无效")?
        {
            bail!("运行材料损坏：{name}")
        }
    }
    Ok(data)
}

pub fn private_json(path: &Path, value: &Value) -> Result<()> {
    ordinary(path, false)?;
    let mut f = OpenOptions::new()
        .create_new(true)
        .write(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    f.write_all(&serde_json::to_vec_pretty(value)?)?;
    f.sync_all()?;
    Ok(())
}

pub fn read_json(path: &Path) -> Result<Value> {
    ordinary(path, true)?;
    Ok(serde_json::from_slice(&fs::read(path)?)?)
}

pub fn python(
    root: &Path,
    action: &str,
    request: Option<&Path>,
    job: Option<&Path>,
) -> Result<Command> {
    if !["selfcheck", "firmware", "device", "recovery"].contains(&action) {
        bail!("动作不支持")
    }
    let mut c = Command::new(root.join("python/bin/python3.14"));
    c.env_clear()
        .env("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")
        .env("HOME", root)
        .env("PYTHONDONTWRITEBYTECODE", "1")
        .arg("-I")
        .arg("-S")
        .arg(root.join("bootstrap.py"))
        .arg(action);
    if let Some(p) = request {
        c.arg(p);
    }
    if let Some(p) = job {
        c.arg(p);
    }
    Ok(c)
}

pub fn execute(
    root: &Path,
    action: &str,
    request: Option<&Path>,
    job: Option<&Path>,
) -> Result<Value> {
    let out = python(root, action, request, job)?.output()?;
    if let Some(dir) = job {
        fs::write(dir.join("engine.log"), &out.stdout)?;
        fs::write(dir.join("engine.stderr"), &out.stderr)?;
    }
    let text = String::from_utf8_lossy(&out.stdout);
    let last = text.lines().last().context("运行引擎没有回执")?;
    let value: Value = serde_json::from_str(last).context("运行引擎回执无效")?;
    if !out.status.success() {
        bail!(
            "{}",
            value["error"]
                .as_str()
                .unwrap_or("引擎执行失败，请查看日志")
        )
    }
    value.get("result").cloned().context("缺少执行结果")
}

pub fn password_hash(mut password: String) -> Result<String> {
    let n = password.chars().count();
    if !(8..=128).contains(&n)
        || password.len() > 512
        || password.chars().any(|c| c < ' ' || c == '\u{7f}')
    {
        bail!("SSH密码需要8至128个非控制字符，最多512字节")
    }
    let random = uuid::Uuid::new_v4().simple().to_string();
    let salt = &random[..16];
    let params =
        sha_crypt::Sha512Params::new(10_000).map_err(|e| anyhow::anyhow!("哈希参数无效：{e:?}"))?;
    let value = sha_crypt::sha512_crypt_b64(password.as_bytes(), salt.as_bytes(), &params);
    // 清零后每个字节都是有效UTF-8，字符串长度不变；明文不进入子进程或文件。
    unsafe { password.as_bytes_mut().fill(0) };
    let encoded = value.map_err(|e| anyhow::anyhow!("密码哈希失败：{e:?}"))?;
    Ok(format!("$6$rounds=10000${salt}${encoded}"))
}

pub fn quote(text: &str) -> String {
    format!("'{}'", text.replace('\'', "'\\''"))
}

pub fn lock(path: &Path) -> Result<File> {
    let f = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW)
        .open(path)?;
    // 文件句柄在进程内保持存活；非阻塞锁阻止多个窗口或应用副本并行执行。
    if unsafe { libc::flock(f.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        bail!("已有一个客户端或设备任务正在运行")
    }
    Ok(f)
}
use std::os::fd::AsRawFd;

fn copy_engine(source: &Path, target: &Path, manifest: &Value) -> Result<()> {
    fs::create_dir_all(target)?;
    fs::set_permissions(target, fs::Permissions::from_mode(0o700))?;
    for name in manifest["files"]
        .as_object()
        .context("清单无效")?
        .keys()
        .chain(std::iter::once(&"integrity.json".to_owned()))
    {
        let from = source.join(name);
        let to = target.join(name);
        if let Some(parent) = to.parent() {
            fs::create_dir_all(parent)?;
        }
        ordinary(&from, true)?;
        fs::copy(&from, &to)?;
    }
    verify(target)?;
    Ok(())
}

pub fn privileged(request_path: &Path) -> Result<()> {
    if unsafe { libc::geteuid() } != 0 {
        bail!("此入口需要macOS系统授权")
    }
    ordinary(request_path, true)?;
    let meta = fs::metadata(request_path)?;
    if meta.uid() == 0 || meta.nlink() != 1 || meta.mode() & 0o077 != 0 {
        bail!("请求文件必须属于普通用户且仅本人可读写")
    }
    let parent = request_path.parent().context("请求目录无效")?;
    let pm = fs::metadata(parent)?;
    if pm.uid() != meta.uid() || pm.mode() & 0o077 != 0 {
        bail!("任务目录权限无效")
    }
    let request = read_json(request_path)?;
    if !["backup", "update", "ssh_start", "ssh_stop"]
        .contains(&request["kind"].as_str().unwrap_or(""))
    {
        bail!("提权动作无效")
    }
    let global = lock(Path::new("/private/tmp/local.a7r5.studio.device.lock"))?;
    if global.metadata()?.uid() != 0 {
        bail!("设备锁所有者无效")
    }
    let root = engine()?;
    let manifest = verify(&root)?;
    let temporary = tempfile::Builder::new()
        .prefix("a7r5-authorized-")
        .tempdir_in("/private/tmp")?;
    let isolated = temporary.path().join("engine");
    copy_engine(&root, &isolated, &manifest)?;
    let work = temporary.path().join("job");
    fs::create_dir(&work)?;
    let input = temporary.path().join("request.json");
    private_json(&input, &request)?;
    // 设备事务开始后，导出失败不得由临时目录析构器清除唯一现场。
    let preserved = temporary.keep();
    let outcome = execute(&isolated, "device", Some(&input), Some(&work));
    let mut result=outcome.unwrap_or_else(|e|json!({"error":e.to_string(),"task_complete":false,"device_IO":work.join("ATTEMPT_LOCK").exists(),"can_replug":false}));
    if result.get("backup_relative").is_some() {
        result["backup_file"] = json!(parent
            .join("device")
            .join(result["backup_relative"].as_str().context("备份路径无效")?));
    }
    // 根权限结束后才向用户目录导出，避免跟随可变目标写入系统路径。
    fn ownership(path: &Path, uid: u32, gid: u32) -> Result<()> {
        let m = fs::symlink_metadata(path)?;
        if m.file_type().is_symlink() {
            bail!("导出材料出现符号链接")
        }
        if m.is_dir() {
            for row in fs::read_dir(path)? {
                ownership(&row?.path(), uid, gid)?;
            }
        }
        use std::os::unix::ffi::OsStrExt;
        let c = std::ffi::CString::new(path.as_os_str().as_bytes())?;
        if unsafe { libc::chown(c.as_ptr(), uid, gid) } != 0 {
            bail!("导出权限设置失败")
        };
        Ok(())
    }
    ownership(&preserved, meta.uid(), meta.gid())
        .with_context(|| format!("现场保留于 {}", preserved.display()))?;
    // 只有固定的三个身份切换调用使用FFI；每个返回值和最终身份均核对。
    if unsafe { libc::setgroups(0, std::ptr::null()) } != 0
        || unsafe { libc::setgid(meta.gid()) } != 0
        || unsafe { libc::setuid(meta.uid()) } != 0
        || unsafe { libc::geteuid() } != meta.uid()
    {
        bail!("无法安全退出管理员身份")
    }
    fs::rename(&work, parent.join("device"))
        .with_context(|| format!("导出失败，现场保留于 {}", preserved.display()))?;
    private_json(&parent.join("privileged-result.json"), &result).with_context(|| {
        format!(
            "导出回执失败，材料保留于 {}，任务目录为 {}",
            preserved.display(),
            parent.display()
        )
    })?;
    fs::remove_dir_all(&preserved)?;
    drop(global);
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn quoting_keeps_shell_literals() {
        assert_eq!(quote("a'b;$()"), "'a'\\''b;$()'");
    }
    #[test]
    fn paths_reject_escape_and_links() {
        let t = tempfile::tempdir().unwrap();
        let p = t.path().join("link");
        std::os::unix::fs::symlink("/etc/passwd", &p).unwrap();
        assert!(ordinary(&p, true).is_err());
        assert!(ordinary(Path::new("/tmp/../etc/passwd"), true).is_err());
        assert!(ordinary(Path::new("/dev/disk0"), true).is_err());
    }
    #[test]
    fn receipts_are_exclusive_private() {
        let t = tempfile::tempdir().unwrap();
        let p = t.path().canonicalize().unwrap().join("receipt");
        private_json(&p, &json!({"ok":true})).unwrap();
        assert_eq!(fs::metadata(&p).unwrap().mode() & 0o777, 0o600);
        assert!(private_json(&p, &json!({})).is_err());
    }
    #[test]
    fn one_process_lock() {
        let t = tempfile::tempdir().unwrap();
        let p = t.path().join("lock");
        let a = lock(&p).unwrap();
        assert!(lock(&p).is_err());
        drop(a);
        assert!(lock(&p).is_ok());
    }
    #[test]
    fn bundled_password_hash_accepts_symbols_without_files() {
        let h = password_hash("Test$;你好123!".to_owned()).unwrap();
        assert!(h.starts_with("$6$rounds=10000$"));
        assert_eq!(h.len(), 119);
        assert!(password_hash("short".to_owned()).is_err());
    }
    #[test]
    fn hash_matches_independent_openssl_fixture() {
        let params = sha_crypt::Sha512Params::new(10_000).unwrap();
        let actual =
            sha_crypt::sha512_crypt_b64("Test$;你好123!".as_bytes(), b"0123456789abcdef", &params)
                .unwrap();
        assert_eq!(actual,"8X9k6wqs3y13Xxao0VOPqFsbkHSt3Uewq0R6/dq6uWPUaE9PFW50UkRn2milbALbs2SV9MmTRc83S.71KfwGa0");
    }
}
