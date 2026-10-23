//! Explicit read-only live probe. Never reads saved configuration or prints identity/session data.
use ysu_auth::{AuthClient, Config};

#[tokio::main(flavor = "current_thread")]
async fn main() {
    let command = std::env::args().nth(1).unwrap_or_else(|| "status".into());
    let client = AuthClient::new(Config {
        operation_timeout: 30,
        ..Config::default()
    })
    .expect("default configuration is valid");
    let result = match command.as_str() {
        "status" => client.status().await.map(|value| {
            serde_json::json!({
                "online": value.online,
                "service": value.service,
                "identity_present": !value.user.is_empty(),
                "ip_present": !value.ip.is_empty()
            })
        }),
        "info" => client.info().await.map(|value| {
            serde_json::json!({
                "online": value["online"],
                "fields_present": value["fields"].as_array().is_some_and(|v| !v.is_empty()),
                "items_present": value["items"].as_array().is_some_and(|v| !v.is_empty())
            })
        }),
        _ => {
            eprintln!("expected status or info");
            std::process::exit(1);
        }
    };
    match result {
        Ok(value) => println!("{value}"),
        Err(error) => {
            println!(
                "{}",
                serde_json::json!({"error_code": error.code, "diagnostic": error.diagnostic()})
            );
            std::process::exit(error.code);
        }
    }
}
