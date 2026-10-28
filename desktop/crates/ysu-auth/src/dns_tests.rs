use super::*;
use std::{net::Ipv4Addr, sync::Arc};
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn dns_error() -> io::Error {
    io::Error::new(io::ErrorKind::NotFound, "fixture DNS failure")
}

#[test]
fn fallback_data_contains_only_the_two_exact_campus_hosts() {
    let data: serde_json::Value = serde_json::from_str(ADDRESSES).unwrap();
    assert_eq!(data["version"], 1);
    assert_eq!(data["addresses"].as_object().unwrap().len(), 2);
    for host in ["auth1.ysu.edu.cn", "cer.ysu.edu.cn"] {
        let address = fallback_ip(host).unwrap();
        assert!(!address.is_loopback());
        assert!(!address.is_unspecified());
        assert!(!address.is_multicast());
    }
    for host in [
        "outside.invalid",
        "auth1.ysu.edu.cn.outside.invalid",
        "127.0.0.1",
        "auth1.ysu.edu.cn.",
    ] {
        assert!(fallback_ip(host).is_none(), "{host}");
    }
}

#[tokio::test]
async fn working_dns_wins_over_fallback_and_retains_all_addresses() {
    let addresses = vec![
        "192.0.2.1:0".parse().unwrap(),
        "[2001:db8::1]:0".parse().unwrap(),
    ];
    let selected = choose_addresses(
        Some(Ipv4Addr::LOCALHOST.into()),
        async { Ok(addresses.clone()) },
        Duration::from_secs(1),
    )
    .await
    .unwrap();
    assert_eq!(selected, addresses);
}

#[tokio::test]
async fn failed_empty_or_stalled_known_dns_uses_only_the_connection_ip() {
    let fallback: IpAddr = "192.0.2.2".parse().unwrap();
    let expected = vec![SocketAddr::new(fallback, 0)];
    assert_eq!(
        choose_addresses(
            Some(fallback),
            async { Err(dns_error()) },
            Duration::from_millis(5),
        )
        .await
        .unwrap(),
        expected
    );
    assert_eq!(
        choose_addresses(
            Some(fallback),
            async { Ok(Vec::new()) },
            Duration::from_millis(5),
        )
        .await
        .unwrap(),
        expected
    );
    assert_eq!(
        choose_addresses(
            Some(fallback),
            std::future::pending(),
            Duration::from_millis(5),
        )
        .await
        .unwrap(),
        expected
    );
}

#[tokio::test]
async fn unlisted_hosts_keep_the_original_error_and_outer_budget() {
    let error = choose_addresses(None, async { Err(dns_error()) }, Duration::from_millis(1))
        .await
        .unwrap_err();
    assert_eq!(error.kind(), io::ErrorKind::NotFound);
    assert!(tokio::time::timeout(
        Duration::from_millis(5),
        choose_addresses(None, std::future::pending(), Duration::from_millis(1)),
    )
    .await
    .is_err());
}

struct FixtureResolver;
impl Resolve for FixtureResolver {
    fn resolve(&self, name: Name) -> Resolving {
        assert_eq!(name.as_str(), "portal.fixture.invalid");
        Box::pin(async {
            let addresses = choose_addresses(
                Some(Ipv4Addr::LOCALHOST.into()),
                std::future::pending(),
                LOOKUP_BUDGET,
            )
            .await?;
            Ok(Box::new(addresses.into_iter()) as Addrs)
        })
    }
}

#[tokio::test]
async fn reqwest_keeps_original_host_url_port_and_sends_the_body_once() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let port = listener.local_addr().unwrap().port();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut request = Vec::new();
        while !request.ends_with(b"\r\n\r\n") {
            let mut byte = [0];
            stream.read_exact(&mut byte).await.unwrap();
            request.push(byte[0]);
            assert!(request.len() < 65536);
        }
        let mut body = [0; 7];
        stream.read_exact(&mut body).await.unwrap();
        assert_eq!(&body, b"fixture");
        stream
            .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
            .await
            .unwrap();
        String::from_utf8(request).unwrap().to_lowercase()
    });
    let client = reqwest::Client::builder()
        .no_proxy()
        .dns_resolver(Arc::new(FixtureResolver))
        .timeout(Duration::from_secs(2))
        .build()
        .unwrap();
    let url = format!("http://portal.fixture.invalid:{port}/submit");
    let response = client.post(&url).body("fixture").send().await.unwrap();
    assert_eq!(response.url().as_str(), url);
    assert_eq!(response.text().await.unwrap(), "ok");
    let request = server.await.unwrap();
    assert!(request.starts_with("post /submit http/1.1\r\n"));
    assert!(request.contains(&format!("host: portal.fixture.invalid:{port}\r\n")));
}
