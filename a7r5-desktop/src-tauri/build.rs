fn main() {
    println!("cargo:rerun-if-changed=engine.sha256");
    println!("cargo:rerun-if-changed=../web");
    tauri_build::build()
}
