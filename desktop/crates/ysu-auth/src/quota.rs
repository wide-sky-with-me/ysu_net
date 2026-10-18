//! Conservative evidence from raw account items, never deduplicated display summaries.
//! Decision: .agents/notes/proposals/accounts/2026-10-14-account-rotation.md
use crate::AuthError;
use regex::Regex;
use serde::Serialize;
use serde_json::Value;
use std::sync::LazyLock;
use unicode_general_category::{get_general_category, GeneralCategory};

const MAX_DEPTH: usize = 6;
const MAX_ITEMS: usize = 256;
const MAX_TEXT_BYTES: usize = 4096;
const MAX_DIGITS: usize = 128;
const UNITS: [&str; 9] = ["B", "KB", "MB", "GB", "TB", "KiB", "MiB", "GiB", "TiB"];

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum QuotaState {
    Unknown,
    Available,
    ZeroReported,
    Unlimited,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct Quota {
    pub state: QuotaState,
    pub message: String,
}

impl Quota {
    fn new(state: QuotaState) -> Self {
        let message = match state {
            QuotaState::Unknown => "剩余流量证据未知",
            QuotaState::Available => "门户报告剩余流量为正值",
            QuotaState::ZeroReported => "门户报告剩余流量为零",
            QuotaState::Unlimited => "门户报告不限量（合成规则，非生产样本）",
        };
        Self {
            state,
            message: message.into(),
        }
    }
}

pub(crate) fn successful_envelope(raw: &Value) -> bool {
    raw.as_object().is_some_and(|object| {
        !object.get("result").is_some_and(|v| v != "success")
            && !object
                .get("code")
                .is_some_and(|v| !matches!(v.as_i64(), Some(0 | 200)))
            && !object.get("success").is_some_and(|v| v != true)
            && !object.get("online").is_some_and(|v| v != true)
    })
}

// Inspect every wrapper instead of taking the first leaf or merging duplicate titles.
fn account_items(raw: &Value) -> Option<&Vec<Value>> {
    let mut current = raw;
    let mut found = None;
    for _ in 0..MAX_DEPTH {
        let object = current.as_object()?;
        if !successful_envelope(current) {
            return None;
        }
        if let Some(value) = object.get("accountInfo").filter(|v| !v.is_null()) {
            let items = value.as_array()?;
            if items.len() > MAX_ITEMS || found.is_some() {
                return None;
            }
            found = Some(items);
        }
        match object.get("data") {
            None | Some(Value::Null) => return found,
            Some(next) => current = next,
        }
    }
    None
}

pub(crate) fn require_account(raw: &Value) -> Result<(), AuthError> {
    account_items(raw)
        .map(|_| ())
        .ok_or_else(|| AuthError::query("账户查询未返回有效原始条目，剩余流量未知"))
}

// A deliberately small, identical fragment grammar in Rust and Python. Unknown/malformed
// markup fails closed; hidden blocks are opaque and never contribute numeric evidence.
fn plain_text(value: &Value) -> Option<String> {
    let source = match value {
        Value::String(s) if s.len() <= MAX_TEXT_BYTES => s.clone(),
        Value::Number(n) => n.as_i64()?.to_string(),
        _ => return None,
    };
    if source.len() > MAX_TEXT_BYTES {
        return None;
    }
    static HIDDEN: LazyLock<[Regex; 3]> = LazyLock::new(|| {
        ["script", "style", "noscript"].map(|tag| {
            let tag = tag
                .chars()
                .map(|ch| format!("[{ch}{}]", ch.to_ascii_uppercase()))
                .collect::<String>();
            Regex::new(&format!(
                r"(?s)<{tag}(?:[ \t\r\n\x0c][^<>]*)?>.*?</{tag}[ \t\r\n\x0c]*>"
            ))
            .expect("constant regex")
        })
    });
    static TAG: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"^</?([A-Za-z][A-Za-z0-9]*)(?:[ \t\r\n\x0c]+[^<>]*)?[ \t\r\n\x0c]*/?>$")
            .expect("constant regex")
    });
    static ENTITY: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r"&(?:#x[0-9A-Fa-f]+|#[0-9]+|amp|lt|gt|quot|apos|nbsp);")
            .expect("constant regex")
    });
    let mut source = source;
    for hidden in HIDDEN.iter() {
        source = hidden.replace_all(&source, "").into_owned();
    }
    let mut visible = String::new();
    let mut rest = source.as_str();
    while let Some(start) = rest.find('<') {
        visible.push_str(&rest[..start]);
        let end = rest[start..].find('>')? + start;
        let capture = TAG.captures(&rest[start..=end])?;
        let tag = capture[1].to_ascii_lowercase();
        if matches!(tag.as_str(), "script" | "style" | "noscript") {
            return None;
        }
        if matches!(tag.as_str(), "br" | "p" | "div" | "li") {
            visible.push(' ');
        }
        rest = &rest[end + 1..];
    }
    visible.push_str(rest);
    let mut decoded = String::new();
    let mut end = 0;
    for entity in ENTITY.find_iter(&visible) {
        decoded.push_str(&visible[end..entity.start()]);
        let token = &entity.as_str()[1..entity.as_str().len() - 1];
        let ch = match token {
            "amp" => '&',
            "lt" => '<',
            "gt" => '>',
            "quot" => '"',
            "apos" => '\'',
            "nbsp" => '\u{a0}',
            _ => {
                let code = if let Some(hex) = token.strip_prefix("#x") {
                    u32::from_str_radix(hex, 16).ok()?
                } else {
                    token.strip_prefix('#')?.parse::<u32>().ok()?
                };
                char::from_u32(code)?
            }
        };
        decoded.push(ch);
        end = entity.end();
    }
    decoded.push_str(&visible[end..]);
    // Fix the whitespace set instead of relying on platform Unicode versions.
    let mut cleaned = String::new();
    for ch in decoded.chars() {
        if is_space(ch) {
            if !cleaned.is_empty() && !cleaned.ends_with(' ') {
                cleaned.push(' ');
            }
        } else if matches!(
            get_general_category(ch),
            GeneralCategory::Control
                | GeneralCategory::Format
                | GeneralCategory::PrivateUse
                | GeneralCategory::Surrogate
                | GeneralCategory::Unassigned
        ) {
            return None;
        } else {
            cleaned.push(ch);
        }
    }
    Some(cleaned.trim_end_matches(' ').to_owned())
}

fn is_space(ch: char) -> bool {
    matches!(ch as u32, 0x09..=0x0d | 0x20 | 0x85 | 0xa0 | 0x1680
        | 0x2000..=0x200a | 0x2028 | 0x2029 | 0x202f | 0x205f | 0x3000)
}

/// Classify only an unambiguous, explicit remaining-traffic item with a recognized unit.
/// Zero is a portal report, not exact-byte exhaustion. No unit conversion or float math.
pub fn classify_quota(raw: &Value) -> Quota {
    fn evidence(raw: &Value) -> Option<QuotaState> {
        static TITLE: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"^剩余流量(?: ?\( ?([^()]*) ?\)| ?（ ?([^（）]*) ?）)?$")
                .expect("constant regex")
        });
        static DECIMAL: LazyLock<Regex> = LazyLock::new(|| {
            Regex::new(r"^([0-9]+(?:\.[0-9]+)?)(?: ?([A-Za-z]+))?$").expect("constant regex")
        });
        let mut candidate = None;
        for item in account_items(raw)? {
            let object = item.as_object()?;
            let title = plain_text(object.get("title")?)?;
            let Some(title_match) = TITLE.captures(&title) else {
                continue;
            };
            if candidate.is_some() {
                return None;
            }
            let title_unit = title_match
                .get(1)
                .or_else(|| title_match.get(2))
                .map(|v| v.as_str().trim_matches(' '));
            if title_unit.is_some_and(|unit| !UNITS.contains(&unit)) {
                return None;
            }
            let content = plain_text(object.get("content")?)?;
            let state = if matches!(content.as_str(), "不限量" | "无限量") {
                // Synthetic literal rule: no production unlimited sample has been observed.
                if title_unit.is_some() {
                    return None;
                }
                QuotaState::Unlimited
            } else {
                let number = DECIMAL.captures(&content)?;
                let digits = &number[1];
                if digits.bytes().filter(u8::is_ascii_digit).count() > MAX_DIGITS {
                    return None;
                }
                let content_unit = number.get(2).map(|v| v.as_str());
                if content_unit.is_some_and(|unit| !UNITS.contains(&unit))
                    || (title_unit.is_none() && content_unit.is_none())
                    || matches!((title_unit, content_unit), (Some(a), Some(b)) if a != b)
                {
                    return None;
                }
                if digits.bytes().any(|ch| matches!(ch, b'1'..=b'9')) {
                    QuotaState::Available
                } else {
                    QuotaState::ZeroReported
                }
            };
            candidate = Some(state);
        }
        candidate
    }
    Quota::new(evidence(raw).unwrap_or(QuotaState::Unknown))
}
