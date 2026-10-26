//! Cloud-only unit coverage; all OS registration effects are fake/in-memory.
use super::*;
use serde_json::json;
use std::cell::{Cell, RefCell};

struct FakeRegistration {
    enabled: Cell<bool>,
    ignore_mutation: Cell<bool>,
    mutation_error: Cell<bool>,
    fail_read: Cell<usize>,
    reads: Cell<usize>,
    calls: RefCell<Vec<&'static str>>,
    args: RefCell<Vec<String>>,
}

impl FakeRegistration {
    fn new(enabled: bool) -> Self {
        Self {
            enabled: Cell::new(enabled),
            ignore_mutation: Cell::new(false),
            mutation_error: Cell::new(false),
            fail_read: Cell::new(0),
            reads: Cell::new(0),
            calls: RefCell::new(Vec::new()),
            args: RefCell::new(if enabled {
                vec!["--minimized".into()]
            } else {
                Vec::new()
            }),
        }
    }
}

impl Registration for FakeRegistration {
    type Error = &'static str;

    fn is_enabled(&self) -> Result<bool, Self::Error> {
        self.calls.borrow_mut().push("read");
        self.reads.set(self.reads.get() + 1);
        if self.fail_read.get() == self.reads.get() {
            return Err("private fixture registry path");
        }
        Ok(self.enabled.get())
    }

    fn enable(&self) -> Result<(), Self::Error> {
        self.calls.borrow_mut().push("enable");
        if self.mutation_error.get() {
            return Err("private fixture registry path");
        }
        if !self.ignore_mutation.get() {
            self.enabled.set(true);
            *self.args.borrow_mut() = registration_args(None);
        }
        Ok(())
    }

    fn disable(&self) -> Result<(), Self::Error> {
        self.calls.borrow_mut().push("disable");
        if self.mutation_error.get() {
            return Err("private fixture registry path");
        }
        if !self.ignore_mutation.get() {
            self.enabled.set(false);
            self.args.borrow_mut().clear();
        }
        Ok(())
    }
}

fn origin(args: &[&str]) -> LaunchOrigin {
    LaunchOrigin::from_args(&args.iter().map(|arg| (*arg).to_owned()).collect::<Vec<_>>())
}

#[test]
fn launch_visibility_matrix_preserves_manual_legacy_and_smoke_semantics() {
    for autostart in [false, true] {
        for minimized in [false, true] {
            for smoke in [false, true] {
                let origin = LaunchOrigin {
                    autostart,
                    minimized,
                    smoke,
                };
                for preference in [false, true] {
                    for icon in [false, true] {
                        for host in [false, true] {
                            let hidden =
                                !smoke && icon && host && (minimized || (autostart && preference));
                            assert_eq!(origin.show_on_launch(preference, icon, host), !hidden);
                        }
                    }
                }
            }
        }
    }
}

#[test]
fn single_instance_manual_reopens_but_auto_and_legacy_do_not_steal_focus() {
    for args in [
        vec!["app"],
        vec!["app", "--demo", "--config", "/other/profile.json"],
        vec!["app", "--config", "--autostart"],
        vec!["app", "--config=--minimized"],
    ] {
        assert!(origin(&args).show_on_reopen());
    }
    for args in [
        vec!["app", "--autostart"],
        vec!["app", "--minimized"],
        vec!["app", "--autostart", "--minimized"],
        vec!["app", "--demo", "--autostart", "--config", "/other.json"],
    ] {
        assert!(!origin(&args).show_on_reopen());
    }
    assert!(origin(&["app", "--smoke", "--autostart", "--minimized"]).show_on_reopen());
}

#[test]
fn registration_uses_origin_flag_and_keeps_explicit_profile() {
    assert_eq!(registration_args(None), vec!["--autostart"]);
    assert_eq!(
        registration_args(Some("/fixture/profile.json")),
        vec!["--autostart", "--config", "/fixture/profile.json"]
    );
}

#[test]
fn getter_is_read_only_and_errors_are_fixed() {
    let manager = FakeRegistration::new(true);
    let before = manager.args.borrow().clone();
    assert!(read_enabled(&manager).unwrap());
    assert_eq!(*manager.args.borrow(), before);
    assert_eq!(*manager.calls.borrow(), vec!["read"]);
    manager.fail_read.set(2);
    assert_eq!(read_enabled(&manager).unwrap_err(), READ_ERROR);
    assert_eq!(*manager.args.borrow(), before);
}

#[test]
fn toggles_require_matching_readback_after_successful_mutation() {
    let manager = FakeRegistration::new(false);
    set_enabled(&manager, true, false, false).unwrap();
    set_enabled(&manager, false, false, false).unwrap();
    assert_eq!(
        *manager.calls.borrow(),
        vec!["enable", "read", "disable", "read"]
    );
    for desired in [false, true] {
        let manager = FakeRegistration::new(!desired);
        manager.ignore_mutation.set(true);
        assert_eq!(
            set_enabled(&manager, desired, false, false).unwrap_err(),
            VERIFY_ERROR
        );
    }
}

#[test]
fn mutation_and_readback_failures_never_expose_dependency_errors() {
    for desired in [false, true] {
        let manager = FakeRegistration::new(!desired);
        manager.mutation_error.set(true);
        assert_eq!(
            set_enabled(&manager, desired, false, false).unwrap_err(),
            WRITE_ERROR
        );
        assert_eq!(manager.reads.get(), 0);
        manager.mutation_error.set(false);
        manager.fail_read.set(1);
        assert_eq!(
            set_enabled(&manager, desired, false, false).unwrap_err(),
            READ_ERROR
        );
    }
}

#[tokio::test]
async fn demo_and_busy_reject_before_any_os_or_storage_call() {
    for (demo, busy, error) in [(true, false, DEMO_ERROR), (false, true, BUSY_ERROR)] {
        let manager = FakeRegistration::new(true);
        for desired in [false, true] {
            assert_eq!(
                set_enabled(&manager, desired, demo, busy).unwrap_err(),
                error
            );
            let result = set_mode(&manager, desired, demo, busy, |_| async {
                panic!("guard must run before preference I/O")
            })
            .await;
            assert_eq!(result.unwrap_err(), error);
        }
        assert!(manager.calls.borrow().is_empty());
    }
}

#[tokio::test]
async fn mode_change_with_os_disabled_only_persists_and_returns_full_snapshot() {
    for minimized in [false, true] {
        let manager = FakeRegistration::new(false);
        let expected = json!({
            "sequence":42, "prefs":{"autostart_minimized":minimized},
            "config":{"username":"fixture"}, "status":null, "accounts":{},
            "auto":{}, "busy":false, "busy_message":"", "info":null,
            "info_error":"", "logs":[], "environment":{}
        });
        let saved = set_mode(&manager, minimized, false, false, |value| {
            assert_eq!(value, minimized);
            assert_eq!(*manager.calls.borrow(), vec!["read"]);
            assert!(!manager.enabled.get());
            std::future::ready(Ok(expected.clone()))
        })
        .await
        .unwrap();
        assert_eq!(saved, expected);
        assert_eq!(*manager.calls.borrow(), vec!["read"]);
        assert!(!manager.enabled.get());
    }
}

#[tokio::test]
async fn enabled_legacy_entry_is_refreshed_and_verified_before_mode_persistence() {
    for minimized in [false, true] {
        let manager = FakeRegistration::new(true);
        set_mode(&manager, minimized, false, false, |value| {
            assert_eq!(value, minimized);
            assert_eq!(*manager.calls.borrow(), vec!["read", "enable", "read"]);
            assert_eq!(*manager.args.borrow(), registration_args(None));
            std::future::ready(Ok(json!({"prefs":{"autostart_minimized":minimized}})))
        })
        .await
        .unwrap();
    }
}

#[tokio::test]
async fn registration_failure_never_reaches_preference_persistence() {
    for failure in ["initial_read", "enable", "verification"] {
        let manager = FakeRegistration::new(true);
        let expected = match failure {
            "initial_read" => {
                manager.fail_read.set(1);
                READ_ERROR
            }
            "enable" => {
                manager.mutation_error.set(true);
                WRITE_ERROR
            }
            _ => {
                manager.fail_read.set(2);
                READ_ERROR
            }
        };
        let result = set_mode(&manager, false, false, false, |_| async {
            panic!("failed registration must not persist a preference")
        })
        .await;
        assert_eq!(result.unwrap_err(), expected);
    }
}

#[tokio::test]
async fn failed_preference_save_keeps_old_intent_after_safe_origin_migration() {
    let manager = FakeRegistration::new(true);
    let old_intent = Cell::new(true);
    let result = set_mode(&manager, false, false, false, |_| async {
        Err(crate::storage::SAVE_ERROR.to_owned())
    })
    .await;
    assert_eq!(result.unwrap_err(), crate::storage::SAVE_ERROR);
    assert!(old_intent.get());
    assert!(manager.enabled.get());
    assert_eq!(*manager.args.borrow(), registration_args(None));
    let migrated = LaunchOrigin {
        autostart: true,
        ..LaunchOrigin::default()
    };
    assert!(!migrated.show_on_launch(old_intent.get(), true, true));
}
