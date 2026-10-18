use regex::Regex;
use scraper::{ElementRef, Html};
use serde_json::{json, Value};
use std::sync::LazyLock;
use unicode_general_category::{get_general_category, GeneralCategory};

pub(crate) fn text(value: &Value) -> String {
    let source = match value {
        Value::String(s) => s.clone(),
        Value::Number(n) => n.to_string(),
        _ => return String::new(),
    };
    static ANSI: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")
            .expect("constant regex")
    });
    let source = ANSI.replace_all(&source, "");
    let html = Html::parse_fragment(&source);
    let mut parts = String::new();
    // Iterative traversal prevents deeply nested portal HTML from overflowing the stack.
    let mut pending = html
        .root_element()
        .children()
        .rev()
        .map(|node| (node, false))
        .collect::<Vec<_>>();
    while let Some((node, closing)) = pending.pop() {
        if let Some(element) = ElementRef::wrap(node) {
            let name = element.value().name();
            if matches!(name, "script" | "style" | "noscript") {
                continue;
            }
            let separator = matches!(name, "br" | "p" | "div" | "li");
            if separator {
                parts.push(' ');
            }
            if !closing {
                if separator {
                    pending.push((node, true));
                }
                pending.extend(element.children().rev().map(|child| (child, false)));
            }
        } else if let Some(text) = node.value().as_text() {
            parts.push_str(text);
        }
    }
    let cleaned: String = parts
        .chars()
        .filter_map(|c| {
            if c.is_whitespace() {
                Some(' ')
            } else if matches!(
                get_general_category(c),
                GeneralCategory::Control
                    | GeneralCategory::Format
                    | GeneralCategory::PrivateUse
                    | GeneralCategory::Surrogate
                    | GeneralCategory::Unassigned
            ) {
                None
            } else {
                Some(c)
            }
        })
        .collect();
    cleaned
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(2048)
        .collect()
}

pub(crate) fn summary(online: &Value, account: &Value) -> Value {
    let info = &online["data"]["portalOnlineUserInfo"];
    let mut current = account;
    let mut inner = &Value::Null;
    for _ in 0..6 {
        if !current.is_object() {
            break;
        }
        if current["accountInfo"].is_array() {
            inner = current;
            break;
        }
        if current.get("name").is_some() || current.get("service").is_some() {
            inner = current;
        }
        current = &current["data"];
    }
    fn present<'a>(values: &[&'a Value]) -> &'a Value {
        values
            .iter()
            .copied()
            .find(|v| !text(v).is_empty())
            .unwrap_or(&Value::Null)
    }
    let mut fields: Vec<[String; 2]> = Vec::new();
    for (label, value) in [
        ("用户", present(&[&inner["name"], &info["userName"]])),
        ("账号", present(&[&info["userId"], &info["userName"]])),
        ("IP", &info["userIp"]),
        ("SSID", &info["ssid"]),
        (
            "当前服务",
            present(&[
                &info["realServiceName"],
                &info["service"],
                &inner["service"],
            ]),
        ),
    ] {
        let value = text(value);
        if !value.is_empty() {
            fields.push([label.into(), value]);
        }
    }
    let mut items: Vec<[String; 2]> = Vec::new();
    if let Some(raw) = inner["accountInfo"].as_array() {
        for item in raw.iter().take(256) {
            let title = text(&item["title"]).replace("套餐&余额", "套餐与余额");
            let content = text(&item["content"]);
            if title.is_empty() {
                continue;
            }
            if content.is_empty() {
                items.retain(|existing| existing[0] != title);
                continue;
            }
            if let Some(existing) = items.iter_mut().find(|p| p[0] == title) {
                existing[1] = content;
            } else {
                items.push([title, content]);
            }
        }
    }
    json!({"online":true,"fields":fields,"items":items})
}
