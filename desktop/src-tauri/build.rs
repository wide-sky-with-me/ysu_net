fn main() {
    let version =
        std::process::Command::new(std::env::var_os("RUSTC").unwrap_or_else(|| "rustc".into()))
            .arg("--version")
            .output()
            .ok()
            .filter(|output| output.status.success())
            .and_then(|output| String::from_utf8(output.stdout).ok())
            .map(|version| version.trim().to_owned())
            .unwrap_or_else(|| "Rust native".into());
    println!("cargo:rustc-env=YSU_RUST_VERSION={version}");
    tauri_build::build()
}
