//! 以普通用户身份另存完整备份；原任务副本保留，既有目标文件绝不覆盖。
use crate::runtime as rt;
use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::{fs::{self, File, DirBuilder}, os::unix::fs::DirBuilderExt, path::{Path, PathBuf}};

const BYTES: u64 = 25_100_288;
const IMAGE: &str = "partition1.logical.bin";

pub fn validate(parent: &Path) -> Result<()> {
    rt::ordinary(parent, false)?;
    if !parent.is_dir() { bail!("请选择已存在的备份保存目录") }
    Ok(())
}

pub fn prepare(task: &Path, parent: &Path, run: &str) -> Result<()> {
    validate(parent)?;
    if run.len()!=32 || !run.bytes().all(|c| c.is_ascii_digit() || (b'a'..=b'f').contains(&c)) {
        bail!("备份任务号无效")
    }
    let directory=parent.join(format!("A7R5-backup-{run}"));
    // 创建独立目录同时预检写权限；失败发生在授权和任何设备请求之前。
    DirBuilder::new().mode(0o700).create(&directory).context("无法在所选位置创建备份目录")?;
    rt::private_json(&task.join("backup-destination.json"), &json!({"directory":directory,"run_id":run}))?;
    Ok(())
}

fn image_matches(path: &Path, digest: &str) -> Result<()> {
    rt::ordinary(path,true)?;
    if fs::metadata(path)?.len()!=BYTES || rt::hash(path)?!=digest { bail!("备份长度或摘要不符，未覆盖目标") }
    Ok(())
}

fn export(task: &Path, result: &Value, destination: &Value) -> Result<Value> {
    let directory=PathBuf::from(destination["directory"].as_str().context("备份保存目录无效")?);
    validate(&directory)?;
    let digest=result["backup_sha256"].as_str().context("完整备份缺少摘要")?;
    let source=task.join("device/session").join(IMAGE);
    image_matches(&source,digest)?;
    let image=directory.join(IMAGE);
    if image.exists() {
        // 处理中断后只接受已完整写好的同一副本；不同内容停止，不覆盖。
        image_matches(&image,digest)?;
    } else {
        let mut temporary=tempfile::NamedTempFile::new_in(&directory)?;
        std::io::copy(&mut File::open(&source)?,temporary.as_file_mut())?;
        temporary.as_file().sync_all()?;
        image_matches(temporary.path(),digest)?;
        temporary.persist_noclobber(&image).map_err(|error| error.error)?;
    }
    let manifest=directory.join("result.json");
    let mut portable=result.clone();
    portable["backup_file"]=json!(image);
    portable["backup_bytes"]=json!(BYTES);
    portable["source_task_directory"]=json!(task);
    if manifest.exists() {
        if rt::read_json(&manifest)?!=portable { bail!("目标已有不同的结果回执，未覆盖") }
    } else { rt::publish_json(&manifest,&portable)?; }
    File::open(&directory)?.sync_all()?;
    Ok(json!({"ok":true,"directory":directory,"file":image,"manifest":manifest,"sha256":digest}))
}

pub fn finish(task: &Path, result: &mut Value) {
    let destination=task.join("backup-destination.json");
    if result["backup_complete"]!=true || !destination.exists() { return }
    let receipt=task.join("backup-export-result.json");
    let outcome=(|| -> Result<Value> {
        if receipt.exists() {
            let saved=rt::read_json(&receipt)?;
            if saved["ok"]!=true { bail!("{}",saved["error"].as_str().unwrap_or("备份另存失败，未自动重试")) }
            if saved["sha256"]!=result["backup_sha256"] { bail!("另存回执与原备份摘要不符") }
            return Ok(saved)
        }
        let binding=rt::read_json(&destination)?;
        if binding["run_id"]!=result["run_id"] { bail!("备份保存目录与任务不匹配") }
        let saved=export(task,result,&binding)?;
        rt::private_json(&receipt,&saved)?;
        Ok(saved)
    })();
    match outcome {
        Ok(saved) => {
            result["backup_export_directory"]=saved["directory"].clone();
            result["backup_export_file"]=saved["file"].clone();
            result["backup_export_manifest"]=saved["manifest"].clone();
        }
        Err(error) => {
            let message=format!("{error:#}");
            result["backup_export_error"]=json!(message);
            if !receipt.exists() {
                let _=rt::private_json(&receipt,&json!({"ok":false,"error":message}));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture() -> (tempfile::TempDir,PathBuf,PathBuf,Value) {
        let temp=tempfile::tempdir().unwrap();let root=temp.path().canonicalize().unwrap();
        let task=root.join("tasks").join("a".repeat(32));fs::create_dir_all(task.join("device/session")).unwrap();
        let source=task.join("device/session").join(IMAGE);fs::write(&source,vec![b'x';BYTES as usize]).unwrap();
        let parent=root.join("chosen");fs::create_dir(&parent).unwrap();
        let result=json!({"kind":"backup","run_id":"a".repeat(32),"backup_complete":true,
            "task_complete":false,"backup_file":source,"backup_sha256":rt::hash(&source).unwrap(),"error":"清理回执未确认"});
        (temp,task,parent,result)
    }
    #[test]
    fn copies_verified_backup_and_portable_receipt_once_even_if_device_task_failed() {
        let (_temp,task,parent,mut result)=fixture();
        prepare(&task,&parent,&"a".repeat(32)).unwrap();
        finish(&task,&mut result);
        assert!(result.get("backup_export_error").is_none());
        let image=Path::new(result["backup_export_file"].as_str().unwrap());
        image_matches(image,result["backup_sha256"].as_str().unwrap()).unwrap();
        let portable=rt::read_json(Path::new(result["backup_export_manifest"].as_str().unwrap())).unwrap();
        assert_eq!(portable["backup_file"],result["backup_export_file"]);
        assert_eq!(portable["task_complete"],false);
        assert_eq!(fs::read(task.join("device/session").join(IMAGE)).unwrap(),fs::read(image).unwrap());
        let prior=result.clone();finish(&task,&mut result);assert_eq!(result,prior);
    }
    #[test]
    fn rejects_existing_data_and_preserves_internal_backup_without_retry() {
        let (_temp,task,parent,mut result)=fixture();
        prepare(&task,&parent,&"a".repeat(32)).unwrap();
        let binding=rt::read_json(&task.join("backup-destination.json")).unwrap();
        let target=Path::new(binding["directory"].as_str().unwrap()).join(IMAGE);
        fs::write(&target,b"existing-backup").unwrap();finish(&task,&mut result);
        assert!(result["backup_export_error"].as_str().unwrap().contains("未覆盖"));
        assert_eq!(fs::read(&target).unwrap(),b"existing-backup");
        assert!(result["backup_complete"]==true && result["backup_file"].as_str().map(Path::new).unwrap().exists());
        let saved=rt::read_json(&task.join("backup-export-result.json")).unwrap();
        finish(&task,&mut result);assert_eq!(rt::read_json(&task.join("backup-export-result.json")).unwrap(),saved);
    }
    #[test]
    fn rejects_links_and_invalid_destinations_before_any_export() {
        let (_temp,task,parent,result)=fixture();
        let link=parent.with_file_name("link");std::os::unix::fs::symlink(&parent,&link).unwrap();
        assert!(prepare(&task,&link,&"a".repeat(32)).is_err());
        assert!(!task.join("backup-destination.json").exists());
        let mut default_result=result.clone();finish(&task,&mut default_result);assert_eq!(result,default_result);
    }
    #[test]
    fn late_helper_receipt_exports_through_overview_without_rewriting_original_receipt() {
        let (_temp,task,parent,result)=fixture();
        prepare(&task,&parent,&"a".repeat(32)).unwrap();
        rt::private_json(&task.join("privileged-result.json"),&result).unwrap();
        rt::private_json(&task.join("status.json"),&json!({"id":"a".repeat(32),"kind":"backup",
            "created":1,"running":false,"interrupted":true})).unwrap();
        let state=crate::tasks::State {data:task.parent().unwrap().parent().unwrap().into(),
            engine:parent.clone(),busy:std::sync::Mutex::new(false)};
        let view=crate::tasks::overview(&state).unwrap();
        assert!(view["tasks"][0]["result"]["backup_export_manifest"].as_str().map(Path::new).unwrap().is_file());
        assert_eq!(rt::read_json(&task.join("privileged-result.json")).unwrap(),result);
        let exported=rt::read_json(&task.join("backup-export-result.json")).unwrap();
        crate::tasks::overview(&state).unwrap();
        assert_eq!(rt::read_json(&task.join("backup-export-result.json")).unwrap(),exported);
    }
}
