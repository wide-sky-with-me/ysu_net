//! Window-independent tray presentation. Only verified status identifies a live connection.
use serde_json::{json, Value};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Indicator {
    Online,
    Offline,
    Waiting,
    External,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrayView {
    pub status: String,
    pub identity: String,
    pub address: String,
    pub quota: String,
    pub activity: String,
    pub tooltip: String,
    pub indicator: Indicator,
    pub connection_label: String,
    pub connection_enabled: bool,
    pub refresh_enabled: bool,
    pub auto_checked: bool,
    pub auto_enabled: bool,
    pub rotation_checked: bool,
    pub rotation_enabled: bool,
    pub connection_action: &'static str,
}

fn text(value: &Value) -> &str {
    value.as_str().unwrap_or("")
}

pub fn compact(value: &str, limit: usize) -> String {
    let clean: String = value
        .chars()
        .map(|c| if c.is_control() { ' ' } else { c })
        .collect();
    let clean = clean.split_whitespace().collect::<Vec<_>>().join(" ");
    if clean.chars().count() <= limit {
        clean
    } else {
        clean
            .chars()
            .take(limit.saturating_sub(1))
            .chain(['…'])
            .collect()
    }
}

fn utf16_limit(value: &str, limit: usize) -> String {
    if value.encode_utf16().count() <= limit {
        return value.to_owned();
    }
    let mut result = String::new();
    let mut size = 0;
    for c in value.chars() {
        if size + c.len_utf16() >= limit {
            break;
        }
        result.push(c);
        size += c.len_utf16();
    }
    result.push('…');
    result
}

pub fn auto_control_available(snapshot: &Value) -> bool {
    snapshot["auto"]["state"] != "external"
        && (snapshot["busy"] != true || snapshot["auto"]["state"] == "on")
}

fn rotation_available(snapshot: &Value) -> bool {
    if snapshot["accounts"]["auto_switch"] == true {
        return true;
    }
    snapshot["auto"]["state"] == "on"
        && snapshot["prefs"]["auto_reconnect"] == true
        && snapshot["busy"] != true
        && snapshot["accounts"]["environment_override"] != true
        && text(&snapshot["accounts"]["error"]).is_empty()
        && snapshot["accounts"]["items"]
            .as_array()
            .is_some_and(|items| {
                items
                    .iter()
                    .filter(|item| item["enabled"] == true && item["password_set"] == true)
                    .count()
                    >= 2
            })
}

impl TrayView {
    pub fn from_snapshot(snapshot: &Value, running: bool, quitting: bool) -> Self {
        let online = snapshot["status"]["online"].as_bool();
        let external = snapshot["auto"]["state"] == "external";
        let busy = snapshot["busy"] == true;
        let auto = snapshot["auto"]["state"] == "on";
        let active = running && !quitting;
        let credentials = !text(&snapshot["config"]["username"]).is_empty()
            && snapshot["config"]["password_set"] == true;
        let title = if quitting {
            "正在退出"
        } else if !running {
            "核心未就绪"
        } else if busy {
            "正在处理"
        } else if external {
            "外部服务管理"
        } else {
            match online {
                Some(true) => "已连接",
                Some(false) => "未连接",
                None => "状态未知",
            }
        };
        let verified = online == Some(true);
        let identity = if verified {
            format!(
                "{} · {}",
                if text(&snapshot["status"]["service"]).is_empty() {
                    "运营商未提供".into()
                } else {
                    compact(text(&snapshot["status"]["service"]), 18)
                },
                if text(&snapshot["status"]["user"]).is_empty() {
                    "账号未提供".into()
                } else {
                    compact(text(&snapshot["status"]["user"]), 32)
                }
            )
        } else if !text(&snapshot["config"]["username"]).is_empty() {
            format!(
                "待连接账号：{}",
                compact(text(&snapshot["config"]["username"]), 32)
            )
        } else {
            "尚未设置账号".into()
        };
        let address = if verified {
            let ip = text(&snapshot["status"]["ip"]);
            format!(
                "IP：{}",
                if ip.is_empty() {
                    "门户未提供".into()
                } else {
                    compact(ip, 45)
                }
            )
        } else {
            "IP：待连接确认".into()
        };
        let current_info = verified
            && snapshot["info"]["online"] == true
            && snapshot["status"]["user"] == snapshot["config"]["username"]
            && snapshot["status"]["service"] == snapshot["config"]["service"];
        let raw_flow = snapshot["info"]["items"].as_array().and_then(|items| {
            items.iter().find_map(|pair| {
                (text(&pair[0]).contains("剩余流量") && !text(&pair[1]).trim().is_empty())
                    .then(|| compact(text(&pair[1]), 42))
            })
        });
        let quota = if current_info {
            raw_flow
                .map(|value| format!("上次流量：{value}"))
                .or_else(|| {
                    (!text(&snapshot["accounts"]["quota"]["message"]).is_empty())
                        .then(|| compact(text(&snapshot["accounts"]["quota"]["message"]), 48))
                })
                .unwrap_or_else(|| "剩余流量：门户未提供".into())
        } else {
            "剩余流量：待核验".into()
        };
        let activity = if external {
            compact(text(&snapshot["auto"]["message"]), 64)
        } else if busy {
            compact(text(&snapshot["busy_message"]), 64)
        } else {
            snapshot["logs"]
                .as_array()
                .and_then(|logs| logs.last())
                .map(|log| compact(text(&log["message"]), 64))
                .unwrap_or_default()
        };
        let rotation = snapshot["accounts"]["auto_switch"] == true;
        let detail = if busy && !activity.is_empty() {
            &activity
        } else {
            &quota
        };
        let mut tooltip = format!(
            "YSU Net · {title}\n{}\n{}\n{}\n重连：{} · 换号：{}",
            utf16_limit(&identity, 28),
            utf16_limit(&address, 44),
            utf16_limit(detail, 20),
            if auto { "开" } else { "关" },
            if rotation { "开" } else { "关" }
        );
        // Windows NOTIFYICONDATA allows 127 UTF-16 units plus its terminator.
        tooltip = utf16_limit(&tooltip, 127);
        let (connection_label, connection_action) = match online {
            Some(true) => (
                if auto {
                    "断开连接并停止重连"
                } else {
                    "断开连接"
                },
                "logout",
            ),
            Some(false) if credentials => ("连接校园网", "login"),
            Some(false) => ("请先设置账号", "login"),
            None => ("查询连接状态", "status"),
        };
        Self {
            status: format!("YSU Net · {title}"),
            identity,
            address,
            quota,
            activity: if activity.is_empty() {
                "等待后台状态".into()
            } else {
                activity
            },
            tooltip,
            indicator: if external {
                Indicator::External
            } else if busy || online.is_none() || (!verified && auto) {
                Indicator::Waiting
            } else if verified {
                Indicator::Online
            } else {
                Indicator::Offline
            },
            connection_label: connection_label.into(),
            connection_action,
            connection_enabled: active
                && !external
                && !busy
                && (online != Some(false) || credentials),
            refresh_enabled: active && !busy,
            auto_checked: auto,
            auto_enabled: active && auto_control_available(snapshot) && (auto || credentials),
            rotation_checked: rotation,
            rotation_enabled: active && rotation_available(snapshot),
        }
    }

    pub fn request(&self, id: &str) -> Option<(&'static str, Value)> {
        match id {
            "connection" if self.connection_enabled => {
                Some(("action", json!({"name": self.connection_action})))
            }
            "refresh" if self.refresh_enabled => Some(("action", json!({"name": "status"}))),
            "auto" if self.auto_enabled => Some((
                "action",
                json!({"name": "set_auto", "value": !self.auto_checked}),
            )),
            "rotation" if self.rotation_enabled => {
                Some(("rotation", json!({"enabled": !self.rotation_checked})))
            }
            _ => None,
        }
    }
}

#[derive(Default)]
pub struct Updates {
    newest: Option<u64>,
    pending: Option<(TrayView, bool)>,
    pub scheduled: bool,
    pub applied: Option<TrayView>,
}

impl Updates {
    pub fn enqueue(&mut self, sequence: u64, view: TrayView, force: bool) -> bool {
        if self.newest.is_some_and(|newest| sequence < newest) {
            return false;
        }
        self.newest = Some(sequence);
        if !force && self.pending.is_none() && self.applied.as_ref() == Some(&view) {
            return false;
        }
        let force = force || self.pending.as_ref().is_some_and(|(_, force)| *force);
        self.pending = Some((view, force));
        if self.scheduled {
            false
        } else {
            self.scheduled = true;
            true
        }
    }

    pub fn take(&mut self) -> Option<(TrayView, bool)> {
        // One drain per UI turn: publications during native setters must schedule again.
        self.scheduled = false;
        self.pending.take()
    }

    pub fn scheduling_failed(&mut self) {
        self.scheduled = false;
    }
}

pub fn badged_icon(base: &[u8], width: u32, height: u32, indicator: Indicator) -> Vec<u8> {
    let mut pixels = base.to_vec();
    if width < 8 || height < 8 || base.len() != width as usize * height as usize * 4 {
        return pixels;
    }
    let color = match indicator {
        Indicator::Online => [24, 126, 92, 255],
        Indicator::Offline => [102, 120, 143, 255],
        Indicator::Waiting => [181, 111, 21, 255],
        Indicator::External => [0, 110, 156, 255],
    };
    let radius = (width.min(height) as f32 * 0.19).max(2.0);
    let cx = width as f32 - radius - 1.0;
    let cy = height as f32 - radius - 1.0;
    for y in 0..height {
        for x in 0..width {
            let distance = ((x as f32 - cx).powi(2) + (y as f32 - cy).powi(2)).sqrt();
            if distance <= radius + 1.0 {
                let color = if distance > radius {
                    [249, 252, 255, 255]
                } else {
                    color
                };
                let offset = (y as usize * width as usize + x as usize) * 4;
                pixels[offset..offset + 4].copy_from_slice(&color);
            }
        }
    }
    pixels
}

#[cfg(test)]
mod tests {
    use super::*;
    fn snapshot() -> Value {
        json!({"sequence":10,"config":{"username":"student-a","service":"中国移动","password_set":true},
            "status":{"online":true,"service":"中国移动","user":"student-a","ip":"192.0.2.10"},
            "busy":false,"auto":{"state":"on"},"prefs":{"auto_reconnect":true},
            "accounts":{"auto_switch":false,"error":"","environment_override":false,"quota":{"state":"available","message":"80.00 GB"},
                "items":[{"enabled":true,"password_set":true},{"enabled":true,"password_set":true}]},
            "info":{"online":true,"items":[["剩余流量","80.00 GB"]]},"logs":[{"message":"已独立确认在线"}]})
    }
    #[test]
    fn verified_summary_and_requests_use_authoritative_state() {
        let s = snapshot();
        let view = TrayView::from_snapshot(&s, true, false);
        assert_eq!(view.indicator, Indicator::Online);
        assert!(view.identity.contains("中国移动") && view.identity.contains("student-a"));
        assert!(view.tooltip.contains("192.0.2.10") && view.tooltip.contains("80.00 GB"));
        assert_eq!(
            view.request("connection"),
            Some(("action", json!({"name":"logout"})))
        );
        assert_eq!(
            view.request("rotation"),
            Some(("rotation", json!({"enabled":true})))
        );
    }
    #[test]
    fn unknown_queries_instead_of_logging_in_and_hides_stale_quota() {
        let mut s = snapshot();
        s["status"] = Value::Null;
        let view = TrayView::from_snapshot(&s, true, false);
        assert_eq!(view.connection_action, "status");
        assert!(view.status.contains("未知"));
        assert!(!view.tooltip.contains("192.0.2.10") && !view.tooltip.contains("80.00"));
        assert!(view.identity.starts_with("待连接账号"));
    }
    #[test]
    fn offline_and_missing_credentials_have_distinct_commands() {
        let mut s = snapshot();
        s["status"]["online"] = false.into();
        assert_eq!(
            TrayView::from_snapshot(&s, true, false).connection_action,
            "login"
        );
        s["config"]["password_set"] = false.into();
        let view = TrayView::from_snapshot(&s, true, false);
        assert!(!view.connection_enabled);
        assert_eq!(view.request("connection"), None);
    }
    #[test]
    fn external_blocks_network_mutations_but_allows_refresh() {
        let mut s = snapshot();
        s["auto"]["state"] = "external".into();
        let view = TrayView::from_snapshot(&s, true, false);
        assert!(!view.connection_enabled && !view.auto_enabled && !view.rotation_enabled);
        assert!(view.refresh_enabled);
        assert_eq!(view.indicator, Indicator::External);
    }
    #[test]
    fn busy_still_allows_stopping_active_automation() {
        let mut s = snapshot();
        s["busy"] = true.into();
        s["accounts"]["auto_switch"] = true.into();
        let view = TrayView::from_snapshot(&s, true, false);
        assert!(!view.connection_enabled && !view.refresh_enabled);
        assert_eq!(
            view.request("auto"),
            Some(("action", json!({"name":"set_auto","value":false})))
        );
        assert_eq!(
            view.request("rotation"),
            Some(("rotation", json!({"enabled":false})))
        );
        s["auto"]["state"] = "off".into();
        s["accounts"]["auto_switch"] = false.into();
        let view = TrayView::from_snapshot(&s, true, false);
        assert!(!view.auto_enabled && !view.rotation_enabled);
    }
    #[test]
    fn rotation_enable_checks_account_candidates_and_overrides() {
        for field in ["environment_override", "error", "items"] {
            let mut s = snapshot();
            s["accounts"][field] = match field {
                "error" => "读取失败".into(),
                "items" => json!([]),
                _ => true.into(),
            };
            assert!(!TrayView::from_snapshot(&s, true, false).rotation_enabled);
        }
        let mut s = snapshot();
        s["auto"]["state"] = "off".into();
        assert!(!TrayView::from_snapshot(&s, true, false).rotation_enabled);
    }
    #[test]
    fn stale_identity_and_unverified_info_do_not_show_quota() {
        for field in ["user", "service"] {
            let mut s = snapshot();
            s["status"][field] = "other".into();
            assert!(!TrayView::from_snapshot(&s, true, false)
                .tooltip
                .contains("80.00"));
        }
        let mut s = snapshot();
        s["info"] = Value::Null;
        assert!(!TrayView::from_snapshot(&s, true, false)
            .tooltip
            .contains("80.00"));
    }
    #[test]
    fn tooltips_are_bounded_and_never_read_private_fields() {
        let mut s = snapshot();
        s["status"]["user"] = "😀".repeat(100).into();
        s["config"]["password"] = "private-fixture-password".into();
        let view = TrayView::from_snapshot(&s, true, false);
        assert!(view.tooltip.encode_utf16().count() <= 127);
        assert!(!view.tooltip.contains("private-fixture-password"));
        assert_eq!(compact("A\nB\tC", 20), "A B C");
    }
    #[test]
    fn shutdown_and_missing_core_disable_mutations() {
        for (running, quitting) in [(false, false), (true, true)] {
            let view = TrayView::from_snapshot(&snapshot(), running, quitting);
            assert!(
                !view.connection_enabled
                    && !view.refresh_enabled
                    && !view.auto_enabled
                    && !view.rotation_enabled
            );
        }
    }
    #[test]
    fn latest_snapshot_wins_and_failed_apply_can_retry() {
        let mut queue = Updates::default();
        let mut s = snapshot();
        let first = TrayView::from_snapshot(&s, true, false);
        assert!(queue.enqueue(10, first, false));
        s["status"]["online"] = false.into();
        let latest = TrayView::from_snapshot(&s, true, false);
        assert!(!queue.enqueue(12, latest.clone(), false));
        assert!(!queue.enqueue(11, TrayView::from_snapshot(&snapshot(), true, false), false));
        assert_eq!(queue.take(), Some((latest.clone(), false)));
        assert!(queue.take().is_none());
        assert!(queue.enqueue(12, latest.clone(), false));
        queue.take();
        queue.applied = Some(latest.clone());
        queue.take();
        assert!(!queue.enqueue(12, latest.clone(), false));
        assert!(queue.enqueue(12, latest.clone(), true));
        assert_eq!(queue.take(), Some((latest, true)));
    }
    #[test]
    fn taking_a_snapshot_reopens_the_next_ui_scheduling_slot() {
        let mut queue = Updates::default();
        let view = TrayView::from_snapshot(&snapshot(), true, false);
        assert!(queue.enqueue(1, view.clone(), false));
        assert_eq!(queue.take(), Some((view.clone(), false)));
        assert!(!queue.scheduled);
        assert!(queue.enqueue(2, view.clone(), true));
        assert!(!queue.enqueue(3, view.clone(), false));
        assert_eq!(queue.take(), Some((view.clone(), true)));
        assert!(!queue.scheduled);
        assert!(queue.enqueue(3, view, false));
    }
    #[test]
    fn icon_badges_preserve_size_and_brand_pixels() {
        let base = vec![80; 32 * 32 * 4];
        let online = badged_icon(&base, 32, 32, Indicator::Online);
        assert_eq!(online.len(), base.len());
        assert_eq!(&online[..128], &base[..128]);
        assert_ne!(online, badged_icon(&base, 32, 32, Indicator::Offline));
        assert_eq!(
            badged_icon(&[], 32, 32, Indicator::Online),
            Vec::<u8>::new()
        );
    }
}
