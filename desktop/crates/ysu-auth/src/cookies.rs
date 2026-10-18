use reqwest::{cookie::CookieStore, header::HeaderValue};
use std::sync::RwLock;
use url::Url;

#[derive(Default)]
pub(crate) struct Jar(RwLock<cookie_store::CookieStore>);

impl CookieStore for Jar {
    fn set_cookies(&self, headers: &mut dyn Iterator<Item = &HeaderValue>, url: &Url) {
        if let Ok(mut store) = self.0.write() {
            for header in headers {
                if let Ok(value) = header.to_str() {
                    let _ = store.parse(value, url);
                }
            }
        }
    }

    fn cookies(&self, url: &Url) -> Option<HeaderValue> {
        let store = self.0.read().ok()?;
        let mut cookies = store.matches(url);
        // Hash-map iteration is not RFC path priority: CAS and Portal can share names.
        cookies.sort_by(|left, right| {
            let left_path: &str = left.path.as_ref();
            let right_path: &str = right.path.as_ref();
            right_path
                .len()
                .cmp(&left_path.len())
                .then_with(|| left.name().cmp(right.name()))
                .then_with(|| left.value().cmp(right.value()))
        });
        if cookies.is_empty() {
            return None;
        }
        let value = cookies
            .iter()
            .map(|cookie| format!("{}={}", cookie.name(), cookie.value()))
            .collect::<Vec<_>>()
            .join("; ");
        HeaderValue::from_str(&value).ok()
    }
}
