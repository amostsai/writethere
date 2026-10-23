fn main() {
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-changed=Cargo.toml");
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("windows") {
        return;
    }
    let mut resource = winresource::WindowsResource::new();
    resource
        .set("FileDescription", "WriteThere")
        .set("ProductName", "WriteThere")
        .set("InternalName", "WriteThere")
        .set("OriginalFilename", "writethere.exe");
    resource
        .compile()
        .expect("could not compile WriteThere Windows version information");
}
