//! Fixed project links for the About page. IPC never accepts a URL or program.
use crate::bridge::CoreBridge;
use serde::{Deserialize, Deserializer, Serialize};
use std::sync::Arc;
use tauri::State;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ProjectLinkTarget {
    Repository,
    Contributors,
}

// Deserialize through String: derived unit enums also accept single-key maps,
// but the IPC contract deliberately permits only these exact string values.
impl<'de> Deserialize<'de> for ProjectLinkTarget {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        match String::deserialize(deserializer)?.as_str() {
            "repository" => Ok(Self::Repository),
            "contributors" => Ok(Self::Contributors),
            _ => Err(serde::de::Error::custom("invalid_target")),
        }
    }
}

impl ProjectLinkTarget {
    fn url(self) -> &'static str {
        match self {
            Self::Repository => "https://github.com/wide-sky-with-me/ysu_net",
            Self::Contributors => "https://github.com/wide-sky-with-me/ysu_net/graphs/contributors",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProjectLinkError {
    UnsupportedEnvironment,
    OpenFailed,
}

// The injected opener keeps unit tests pure; only the enum supplies its URL.
fn open_link_with<E>(
    bridge: &CoreBridge,
    target: ProjectLinkTarget,
    opener: impl FnOnce(&'static str) -> Result<(), E>,
) -> Result<(), ProjectLinkError> {
    if bridge.demo {
        return Err(ProjectLinkError::UnsupportedEnvironment);
    }
    // Do not expose or log plugin errors: they can contain OS paths/details.
    opener(target.url()).map_err(|_| ProjectLinkError::OpenFailed)
}

#[tauri::command]
pub fn project_open_link(
    target: ProjectLinkTarget,
    bridge: State<'_, Arc<CoreBridge>>,
) -> Result<(), ProjectLinkError> {
    open_link_with(bridge.inner().as_ref(), target, |url| {
        // Match updater_open_releases: direct Rust API, default browser only.
        tauri_plugin_opener::open_url(url, None::<&str>)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    const TARGETS: [ProjectLinkTarget; 2] = [
        ProjectLinkTarget::Repository,
        ProjectLinkTarget::Contributors,
    ];

    #[test]
    fn target_accepts_exact_known_strings() {
        assert_eq!(
            serde_json::from_str::<ProjectLinkTarget>(r#""repository""#).unwrap(),
            ProjectLinkTarget::Repository
        );
        assert_eq!(
            serde_json::from_str::<ProjectLinkTarget>(r#""contributors""#).unwrap(),
            ProjectLinkTarget::Contributors
        );
    }

    #[test]
    fn target_rejects_urls_unknown_values_and_non_strings() {
        for value in [
            json!("https://github.com/wide-sky-with-me/ysu_net"),
            json!("https://github.com/wide-sky-with-me/ysu_net/graphs/contributors"),
            json!("https://example.invalid"),
            json!("file:///private/browser"),
            json!("firefox"),
            json!("releases"),
            json!("unknown"),
            json!("Repository"),
            json!("repository "),
            json!(""),
            json!({"repository": null}),
            json!({"contributors": null}),
            json!(["repository"]),
            json!(null),
            json!(true),
            json!(0),
        ] {
            assert!(
                serde_json::from_value::<ProjectLinkTarget>(value.clone()).is_err(),
                "unexpected accepted target: {value}"
            );
        }
    }

    #[test]
    fn targets_open_only_their_fixed_urls() {
        let bridge = CoreBridge::new(false, false);
        let mut opened = Vec::new();
        for target in TARGETS {
            assert_eq!(
                open_link_with(&bridge, target, |url| {
                    opened.push(url);
                    Ok::<(), ()>(())
                }),
                Ok(())
            );
        }
        assert_eq!(
            opened,
            [
                "https://github.com/wide-sky-with-me/ysu_net",
                "https://github.com/wide-sky-with-me/ysu_net/graphs/contributors",
            ]
        );
    }

    #[test]
    fn demo_rejects_every_target_without_calling_opener() {
        let bridge = CoreBridge::new(true, false);
        let mut calls = 0;
        for target in TARGETS {
            let error = open_link_with(&bridge, target, |_| {
                calls += 1;
                Ok::<(), ()>(())
            })
            .unwrap_err();
            assert_eq!(error, ProjectLinkError::UnsupportedEnvironment);
            assert_eq!(
                serde_json::to_value(error).unwrap(),
                json!("unsupported_environment")
            );
        }
        assert_eq!(calls, 0);
    }

    #[test]
    fn smoke_inherits_demo_guard_without_calling_opener() {
        let bridge = CoreBridge::new(false, true);
        for target in TARGETS {
            assert_eq!(
                open_link_with(&bridge, target, |_| -> Result<(), ()> {
                    panic!("smoke mode must never call opener")
                }),
                Err(ProjectLinkError::UnsupportedEnvironment)
            );
        }
    }

    #[test]
    fn opener_failures_have_only_the_stable_public_error() {
        let bridge = CoreBridge::new(false, false);
        for target in TARGETS {
            for detail in [
                "/private/internal/browser: permission denied",
                r"C:\private\browser.exe: OS failure",
            ] {
                let mut calls = 0;
                let error = open_link_with(&bridge, target, |_| {
                    calls += 1;
                    Err::<(), _>(std::io::Error::other(detail))
                })
                .unwrap_err();
                assert_eq!(calls, 1);
                assert_eq!(error, ProjectLinkError::OpenFailed);
                assert_eq!(serde_json::to_value(error).unwrap(), json!("open_failed"));
            }
        }
    }
}
