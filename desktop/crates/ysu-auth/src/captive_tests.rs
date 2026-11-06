use super::*;
use tokio::io::{AsyncReadExt, AsyncWriteExt};

fn http() -> Transport {
    Transport::new(&Config::default(), false).unwrap()
}

fn page(status: u16, body: &str) -> Reply {
    Reply {
        url: Url::parse("http://124.124.124.124/").unwrap(),
        status,
        headers: HeaderMap::new(),
        body: body.as_bytes().to_vec(),
        chain: Vec::new(),
    }
}

#[test]
fn anonymous_bootstrap_requires_the_observed_full_source_and_target() {
    let http = http();
    let source = http.endpoint("eportal/redirect.jsp").unwrap();
    let target = Url::parse("http://124.124.124.124/").unwrap();
    assert!(http.is_captive_bootstrap(&source, &target, &Method::GET, false));
    // The exception is consumed by the dedicated resolver, never by general HTTP.
    assert!(http.allowed(&target).is_err());
    for method in [Method::HEAD, Method::POST] {
        assert!(!http.is_captive_bootstrap(&source, &target, &method, false));
    }
    assert!(!http.is_captive_bootstrap(&source, &target, &Method::GET, true));
    for source in [
        "https://auth1.ysu.edu.cn/",
        "https://auth1.ysu.edu.cn/eportal/index.jsp",
        "https://auth1.ysu.edu.cn/eportal/redirect.jsp?mode=history",
        "https://auth1.ysu.edu.cn/eportal/redirect.jsp?",
        "https://auth1.ysu.edu.cn/eportal/redirect.jsp#fixture",
        "https://cer.ysu.edu.cn/eportal/redirect.jsp",
        "http://auth1.ysu.edu.cn/eportal/redirect.jsp",
    ] {
        assert!(!http.is_captive_bootstrap(
            &Url::parse(source).unwrap(),
            &target,
            &Method::GET,
            false
        ));
    }
    for target in [
        "http://124.124.124.124/?mode=history",
        "http://124.124.124.124/?",
        "http://124.124.124.124/#fixture",
        "http://124.124.124.124:81/",
        "http://124.124.124.124/eportal/index.jsp",
        "http://fixture@124.124.124.124/",
        "http://124.124.124.125/",
        "https://124.124.124.124/",
    ] {
        assert!(!http.is_captive_bootstrap(
            &source,
            &Url::parse(target).unwrap(),
            &Method::GET,
            false
        ));
    }
}

#[test]
fn captive_hint_only_returns_a_fresh_same_origin_https_index() {
    let http = http();
    let target = "https://auth1.ysu.edu.cn/eportal/index.jsp?fixture=opaque&amp;other=one";
    let reply = page(200, &format!("<script>location.href='{target}'</script>"));
    let actual = http.captive_page_target(&reply).unwrap();
    assert_eq!(actual.query(), Some("fixture=opaque&other=one"));
    for target in [
        "http://auth1.ysu.edu.cn/eportal/index.jsp?fixture=opaque",
        "https://outside.invalid/eportal/index.jsp?fixture=opaque",
        "https://auth1.ysu.edu.cn:444/eportal/index.jsp?fixture=opaque",
        "https://auth1.ysu.edu.cn/portal/portal-main?sessionId=fixture-session",
        "https://auth1.ysu.edu.cn/eportal/index.jsp?sessionId=fixture-session",
        "https://auth1.ysu.edu.cn/eportal/index.jsp?flowSessionId=fixture-session",
        "https://auth1.ysu.edu.cn/eportal/index.jsp?ticket=fixture-ticket",
        "https://auth1.ysu.edu.cn/eportal/index.jsp#fixture",
        "https://fixture@auth1.ysu.edu.cn/eportal/index.jsp",
    ] {
        let reply = page(200, &format!("<script>location.href='{target}'</script>"));
        assert!(http.captive_page_target(&reply).is_err(), "{target}");
    }
    assert!(http.captive_page_target(&page(302, "")).is_err());
    assert!(http
        .captive_page_target(&page(200, "unrecognized"))
        .is_err());
}

#[tokio::test]
async fn anonymous_client_never_inherits_cookies_or_follows_http_redirects() {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = Url::parse(&format!("http://{}/", listener.local_addr().unwrap())).unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") {
            let mut byte = [0];
            stream.read_exact(&mut byte).await.unwrap();
            bytes.push(byte[0]);
            assert!(bytes.len() < HEADER_LIMIT);
        }
        stream.write_all(b"HTTP/1.1 302 Found\r\nLocation: http://outside.invalid/\r\nSet-Cookie: captive=untrusted; Path=/\r\nContent-Length: 0\r\nConnection: close\r\n\r\n").await.unwrap();
        String::from_utf8(bytes).unwrap().to_lowercase()
    });
    let http = http();
    let cookie = HeaderValue::from_static("portal=private-fixture; Path=/");
    http.jar.set_cookies(&mut std::iter::once(&cookie), &url);
    let op = Operation::new(Instant::now() + Duration::from_secs(3));
    let reply = http.captive_get(&url, &op).await.unwrap();
    assert_eq!(reply.status, 302);
    let sent = server.await.unwrap();
    for header in [
        "cookie:",
        "authorization:",
        "referer:",
        "origin:",
        "x-xsrf-token:",
    ] {
        assert!(!sent.contains(header), "{header}");
    }
    assert!(!http
        .jar
        .cookies(&url)
        .unwrap()
        .to_str()
        .unwrap()
        .contains("captive="));
}

#[tokio::test]
async fn repeated_captive_bootstrap_stops_before_any_network_request() {
    let http = http();
    http.captive_read.store(true, Ordering::SeqCst);
    let error = http
        .clone()
        .resolve_captive_navigation(
            &http.endpoint("eportal/redirect.jsp").unwrap(),
            &Url::parse("http://124.124.124.124/").unwrap(),
            &Method::GET,
            false,
            &Operation::new(Instant::now() + Duration::from_secs(2)),
        )
        .await
        .unwrap_err();
    assert_eq!(error.diagnostic().reason, Reason::RedirectLimit);
}

#[tokio::test]
async fn location_and_api_html_use_the_same_one_shot_captive_resolver() {
    // Mark the one allowed read consumed: the wiring must reach RedirectLimit
    // rather than generic RedirectBlocked, without contacting a campus endpoint.
    let http = http();
    http.captive_read.store(true, Ordering::SeqCst);
    let source = http.endpoint("eportal/redirect.jsp").unwrap();
    let target = Url::parse("http://124.124.124.124/").unwrap();
    let op = Operation::new(Instant::now() + Duration::from_secs(2));
    for kind in [
        NavigationKind::HttpLocation,
        NavigationKind::BrowserDocument,
    ] {
        let error = http
            .resolve_portal_navigation(&source, target.clone(), &Method::GET, false, kind, &op)
            .await
            .unwrap_err();
        assert_eq!(error.diagnostic().reason, Reason::RedirectLimit);
        let navigation = serde_json::to_value(error.diagnostic().navigation.unwrap()).unwrap();
        assert_eq!(navigation["kind"], serde_json::to_value(kind).unwrap());
    }
    for body in [
        "<meta http-equiv='refresh' content='0;url=http://124.124.124.124/'>",
        "<script>window.location.href = 'http://124.124.124.124/';</script>",
        "<script>location.assign('http://124.124.124.124/');</script>",
        "<script>location.replace('http://124.124.124.124/');</script>",
    ] {
        let error = crate::protocol::next_api_portal_navigation(&http, body, &source, &op)
            .await
            .unwrap_err();
        assert_eq!(error.diagnostic().reason, Reason::RedirectLimit);
        let navigation = serde_json::to_value(error.diagnostic().navigation.unwrap()).unwrap();
        assert_eq!(navigation["kind"], "html_navigation");
    }
}

#[tokio::test]
async fn shared_navigation_does_not_spend_the_captive_read_on_unproven_contexts() {
    let http = http();
    let source = http.endpoint("eportal/redirect.jsp").unwrap();
    let target = Url::parse("http://124.124.124.124/").unwrap();
    let op = Operation::new(Instant::now() + Duration::from_secs(2));
    for (source, target, method, has_body) in [
        (source.clone(), target.clone(), Method::POST, false),
        (source.clone(), target.clone(), Method::GET, true),
        (
            source.join("?mode=history").unwrap(),
            target.clone(),
            Method::GET,
            false,
        ),
        (http.cas.clone(), target.clone(), Method::GET, false),
        (
            source.clone(),
            target.join("?fixture=opaque").unwrap(),
            Method::GET,
            false,
        ),
        (source, target.join("other").unwrap(), Method::GET, false),
    ] {
        for kind in [
            NavigationKind::HttpLocation,
            NavigationKind::HtmlNavigation,
            NavigationKind::BrowserDocument,
        ] {
            let error = http
                .resolve_portal_navigation(&source, target.clone(), &method, has_body, kind, &op)
                .await
                .unwrap_err();
            assert_eq!(error.diagnostic().reason, Reason::RedirectBlocked);
            assert!(!http.captive_read.load(Ordering::SeqCst));
        }
    }
}

/// Captured from the campus iYanDa access point on 2026-11-06 while unauthenticated:
/// `GET http://124.124.124.124/` returns this single-script body.
const OBSERVED_IYANDA_HINT: &str = "<script>top.self.location.href='https://auth1.ysu.edu.cn/eportal/index.jsp?wlanuserip=b7108b0da555af8d4318342a5ad5e63f&wlanacname=86aeba9fa75c33973fb184d637669145&ssid=&nasip=9c67ed1ce2373557ba7c2c9af4678f71&snmpagentip=&mac=afcc277df63190b3b80a8bae01568bb1&t=wireless-v2&url=709db9dc9ce334aa02a9e1ee58ba6fcf3bc3349e947ead360ce162a346ea1a973575c2bcf9743cd752b78cd06c8d7eb1&apmac=&nasid=86aeba9fa75c33973fb184d637669145&vid=f4de06d407ac7b7f&port=1dcf032f51eb16cf&nasportid=5b9da5b08a53a540e26b350a596c2af84974a3ad4265b15b82c47758c1e0fbc2'</script>";

#[test]
fn observed_iyanda_hint_resolves_to_the_fresh_https_index() {
    let http = http();
    let target = http
        .captive_page_target(&page(200, OBSERVED_IYANDA_HINT))
        .unwrap();
    assert_eq!(target.scheme(), "https");
    assert_eq!(target.path(), "/eportal/index.jsp");
    assert_eq!(target.host_str(), Some("auth1.ysu.edu.cn"));
    let query = target.query().unwrap();
    assert!(query.contains("wlanuserip="), "{query}");
    assert!(query.contains("t=wireless-v2"), "{query}");
}

#[tokio::test]
async fn anonymous_hint_read_tolerates_a_body_shorter_than_its_declared_length() {
    // Campuses emit a body that ends before the declared length; a strict HTTP client
    // drops the whole hint, while this read keeps the bytes that arrived.
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let url = Url::parse(&format!("http://{}/", listener.local_addr().unwrap())).unwrap();
    let server = tokio::spawn(async move {
        let (mut stream, _) = listener.accept().await.unwrap();
        let mut bytes = Vec::new();
        while !bytes.ends_with(b"\r\n\r\n") {
            let mut byte = [0];
            stream.read_exact(&mut byte).await.unwrap();
            bytes.push(byte[0]);
            assert!(bytes.len() < HEADER_LIMIT);
        }
        let body = "<script>location.href='https://auth1.ysu.edu.cn/eportal/index.jsp?fixture=opaque'</script>";
        let response = format!(
            "HTTP/1.1 200 ok\r\nServer: Apache\r\nContent-Length:  {}\r\nConnection: close\r\n\r\n{}",
            body.len() + 1,
            body
        );
        stream.write_all(response.as_bytes()).await.unwrap();
        drop(stream);
        String::from_utf8(bytes).unwrap().to_lowercase()
    });
    let http = http();
    let op = Operation::new(Instant::now() + Duration::from_secs(3));
    let reply = http.captive_get(&url, &op).await.unwrap();
    assert_eq!(reply.status, 200);
    let request = server.await.unwrap();
    assert!(request.starts_with("get / http/1.1"), "{request}");
    let target = http.captive_page_target(&reply).unwrap();
    assert_eq!(target.query(), Some("fixture=opaque"));
}
