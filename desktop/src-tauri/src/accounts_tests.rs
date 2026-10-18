use super::*;
use serde_json::json;
use std::fs;

fn save(store: &Store, username: &str) -> String {
    store.save_account(json!({"label":"Fixture", "username":username, "password":"fixture-secret-b", "service":"校园网", "backend":"api", "enabled":true})).unwrap();
    store
        .load_accounts(&store.load_config(false).unwrap())
        .unwrap()
        .accounts
        .iter()
        .find(|a| a.username == username)
        .unwrap()
        .id
        .clone()
}

#[test]
fn legacy_account_is_virtual_and_read_does_not_migrate() {
    let store = Store::open(None, true).unwrap();
    let config = store.load_config(false).unwrap();
    let public = store.load_accounts(&config).unwrap().public(&config, false);
    assert_eq!(public["items"][0]["id"], "current");
    assert_eq!(public["items"][0]["current"], true);
    assert!(!public.to_string().contains(&config.password));
    assert!(!store.path.with_extension("accounts.json").exists());
}

#[test]
fn incomplete_active_overlay_never_corrupts_a_valid_saved_book() {
    let store = Store::open(None, true).unwrap();
    let target = save(&store, "fixture-b");
    let mut config = store.prepare_account(&target).unwrap().source;
    let before = fs::read(store.path.with_extension("accounts.json")).unwrap();
    config.password.clear();
    fs::write(&store.path, serde_json::to_vec(&config).unwrap()).unwrap();
    assert!(store.prepare_account(&target).is_err());
    assert_eq!(
        fs::read(store.path.with_extension("accounts.json")).unwrap(),
        before
    );
}

#[test]
fn preparation_preserves_current_and_selects_stable_target() {
    let store = Store::open(None, true).unwrap();
    let target = save(&store, "fixture-b");
    let plan = store.prepare_account(&target).unwrap();
    assert_eq!(plan.source.username, "20260001");
    assert_eq!(plan.target.username, "fixture-b");
    assert_eq!(plan.target_id, target);
    let book = store.load_accounts(&plan.source).unwrap();
    assert_eq!(book.accounts.len(), 2);
    assert!(book.accounts.iter().all(|a| saved_id(&a.id)));
    assert_eq!(store.load_config(false).unwrap().username, "20260001");
}

#[test]
fn commit_merges_new_timing_without_reverting_settings() {
    let store = Store::open(None, true).unwrap();
    let target = save(&store, "fixture-b");
    let plan = store.prepare_account(&target).unwrap();
    store
        .update_config(json!({"check_interval":81}).as_object().unwrap().clone())
        .unwrap();
    let selected = store.commit_account(&plan).unwrap();
    assert_eq!(selected.username, "fixture-b");
    assert_eq!(selected.check_interval, 81);
}

#[test]
fn concurrent_active_credential_and_endpoint_changes_block_commit() {
    for change in [
        json!({"password":"new-active-secret"}),
        json!({"service":"中国移动"}),
        json!({"base":"https://fixture.invalid"}),
        json!({"verify_tls":false}),
    ] {
        let store = Store::open(None, true).unwrap();
        let target = save(&store, "fixture-b");
        let plan = store.prepare_account(&target).unwrap();
        store
            .update_config(change.as_object().unwrap().clone())
            .unwrap();
        assert!(store.commit_account(&plan).is_err());
        assert_eq!(store.load_config(false).unwrap().username, "20260001");
    }
}

#[test]
fn candidate_edit_or_deletion_invalidates_prepared_selection() {
    for operation in ["password", "disabled", "deleted"] {
        let store = Store::open(None, true).unwrap();
        let target = save(&store, "fixture-b");
        let plan = store.prepare_account(&target).unwrap();
        if operation == "deleted" {
            store.delete_account(&target).unwrap();
        } else {
            store.save_account(json!({"id":target,"username":"fixture-b","password":if operation == "password" {"different-secret"} else {""},"service":"校园网","backend":"api","enabled":operation != "disabled"})).unwrap();
        }
        assert!(store.commit_account(&plan).is_err());
    }
}

#[test]
fn latest_legacy_password_is_authoritative_and_preserved_when_leaving() {
    let store = Store::open(None, true).unwrap();
    store.save_account(json!({"id":"current","username":"20260001","password":"","service":"校园网","backend":"api","enabled":true})).unwrap();
    let target = save(&store, "fixture-b");
    store
        .update_config(
            json!({"password":"legacy-new-secret"})
                .as_object()
                .unwrap()
                .clone(),
        )
        .unwrap();
    let config = store.load_config(false).unwrap();
    assert_eq!(
        store
            .load_accounts(&config)
            .unwrap()
            .accounts
            .iter()
            .find(|a| a.username == "20260001")
            .unwrap()
            .password,
        "legacy-new-secret"
    );
    let plan = store.prepare_account(&target).unwrap();
    store.commit_account(&plan).unwrap();
    let raw: Value = serde_json::from_str(
        &fs::read_to_string(store.path.with_extension("accounts.json")).unwrap(),
    )
    .unwrap();
    assert!(raw["accounts"]
        .as_array()
        .unwrap()
        .iter()
        .any(|a| a["username"] == "20260001" && a["password"] == "legacy-new-secret"));
}

#[test]
fn active_account_cannot_be_deleted() {
    let store = Store::open(None, true).unwrap();
    let target = save(&store, "fixture-b");
    let plan = store.prepare_account(&target).unwrap();
    store.commit_account(&plan).unwrap();
    assert!(store.delete_account(&target).is_err());
}

#[test]
fn editing_keeps_password_and_position_but_not_username_changes() {
    let store = Store::open(None, true).unwrap();
    let first = save(&store, "fixture-b");
    save(&store, "fixture-c");
    let update = json!({"id":first,"label":"Renamed","username":"fixture-b","password":"","service":"中国移动","backend":"api","enabled":true});
    store.save_account(update.clone()).unwrap();
    let book = store
        .load_accounts(&store.load_config(false).unwrap())
        .unwrap();
    assert_eq!(book.accounts[0].id, first);
    assert_eq!(book.accounts[0].password, "fixture-secret-b");
    let mut changed = update;
    changed["username"] = "fixture-d".into();
    assert!(store.save_account(changed).is_err());
}

#[test]
fn unknown_and_duplicate_fields_fail_before_writing() {
    let store = Store::open(None, true).unwrap();
    assert!(store.save_account(json!({"username":"fixture-b","password":"","service":"校园网","backend":"api","enabled":true})).is_err());
    assert!(store.save_account(json!({"username":"fixture-b","password":"pw","service":"校园网","backend":"api","enabled":true,"unexpected":true})).is_err());
    save(&store, "fixture-b");
    let bytes = fs::read(store.path.with_extension("accounts.json")).unwrap();
    assert!(store.save_account(json!({"username":"fixture-b","password":"pw","service":"校园网","backend":"api","enabled":true})).is_err());
    assert_eq!(
        fs::read(store.path.with_extension("accounts.json")).unwrap(),
        bytes
    );
}

#[test]
fn malformed_book_never_looks_empty_or_enables_rotation() {
    let store = Store::open(None, true).unwrap();
    for raw in [
        json!({"version":2,"auto_switch":false,"accounts":[]}),
        json!({"version":1,"auto_switch":false,"accounts":[],"extra":1}),
    ] {
        fs::write(store.path.with_extension("accounts.json"), raw.to_string()).unwrap();
        assert!(store
            .load_accounts(&store.load_config(false).unwrap())
            .is_err());
        assert!(store.save_rotation(true).is_err());
    }
}

#[test]
fn rotation_requires_two_enabled_accounts_and_preserves_legacy_identity() {
    let store = Store::open(None, true).unwrap();
    assert!(store.save_rotation(true).is_err());
    save(&store, "fixture-b");
    store.save_rotation(true).unwrap();
    let config = store.load_config(false).unwrap();
    let book = store.load_accounts(&config).unwrap();
    assert!(book.auto_switch);
    assert_eq!(book.accounts.len(), 2);
    assert_eq!(config.username, "20260001");
    store.save_rotation(false).unwrap();
    assert!(!store.load_accounts(&config).unwrap().auto_switch);
}

#[cfg(unix)]
#[test]
fn account_files_remain_private() {
    use std::os::unix::fs::PermissionsExt;
    let store = Store::open(None, true).unwrap();
    save(&store, "fixture-b");
    assert_eq!(
        fs::metadata(store.path.with_extension("accounts.json"))
            .unwrap()
            .permissions()
            .mode()
            & 0o777,
        0o600
    );
}
