use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;

use serde::Serialize;
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{App, AppHandle, Emitter, Runtime};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut};

use crate::window::{show_main_window, toggle_panel_window};

pub const HOTKEY_UNAVAILABLE_MESSAGE: &str = "快捷键不可用，请更换组合后重试。";
pub const HOST_ACTION_EVENT: &str = "reflex://host-action";
pub const DEFAULT_PANEL_HOTKEY: &str = "Alt+Q";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HostAction {
    Open,
    Recent,
    History,
    Plugins,
    Settings,
    Panel,
    Quit,
}

impl HostAction {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Open => "open",
            Self::Recent => "recent",
            Self::History => "history",
            Self::Plugins => "plugins",
            Self::Settings => "settings",
            Self::Panel => "panel",
            Self::Quit => "quit",
        }
    }
}

/// The two independently registered global hotkeys. Both share one
/// registration transaction and cleanup list but keep separate status.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HotkeySlot {
    Main,
    Panel,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct DesktopStatus {
    pub hotkey: String,
    pub hotkey_active: bool,
    pub message: Option<String>,
    pub panel_hotkey: String,
    pub panel_hotkey_active: bool,
    pub panel_message: Option<String>,
}

impl DesktopStatus {
    pub fn active(hotkey: impl Into<String>) -> Self {
        Self {
            hotkey: hotkey.into(),
            hotkey_active: true,
            message: None,
            panel_hotkey: DEFAULT_PANEL_HOTKEY.to_string(),
            panel_hotkey_active: false,
            panel_message: None,
        }
    }

    pub fn unavailable(hotkey: impl Into<String>) -> Self {
        Self {
            hotkey: hotkey.into(),
            hotkey_active: false,
            message: Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string()),
            panel_hotkey: DEFAULT_PANEL_HOTKEY.to_string(),
            panel_hotkey_active: false,
            panel_message: None,
        }
    }

    fn pending(hotkey: impl Into<String>) -> Self {
        Self {
            hotkey: hotkey.into(),
            hotkey_active: false,
            message: None,
            panel_hotkey: DEFAULT_PANEL_HOTKEY.to_string(),
            panel_hotkey_active: false,
            panel_message: None,
        }
    }
}

pub struct DesktopState {
    status: Mutex<DesktopStatus>,
    panel_status: Mutex<DesktopStatus>,
    transaction: Mutex<()>,
    pending_cleanup: Mutex<Vec<String>>,
    tray_available: AtomicBool,
}

impl DesktopState {
    #[cfg(test)]
    pub fn new(hotkey: impl Into<String>) -> Self {
        Self::new_with_panel(hotkey, DEFAULT_PANEL_HOTKEY)
    }

    pub fn new_with_panel(hotkey: impl Into<String>, panel_hotkey: impl Into<String>) -> Self {
        Self {
            status: Mutex::new(DesktopStatus::pending(hotkey)),
            panel_status: Mutex::new(DesktopStatus::pending(panel_hotkey)),
            transaction: Mutex::new(()),
            pending_cleanup: Mutex::new(Vec::new()),
            tray_available: AtomicBool::new(false),
        }
    }

    pub fn status(&self) -> DesktopStatus {
        let mut status = self
            .status
            .lock()
            .map(|status| status.clone())
            .unwrap_or_else(|_| DesktopStatus::unavailable("Ctrl+Alt+R"));
        if let Ok(panel) = self.panel_status.lock() {
            status.panel_hotkey = panel.hotkey.clone();
            status.panel_hotkey_active = panel.hotkey_active;
            status.panel_message = panel.message.clone();
        }
        status
    }

    #[cfg(test)]
    pub fn panel_status(&self) -> DesktopStatus {
        self.panel_status
            .lock()
            .map(|status| status.clone())
            .unwrap_or_else(|_| DesktopStatus::unavailable(DEFAULT_PANEL_HOTKEY))
    }

    fn slot_status(&self, slot: HotkeySlot) -> &Mutex<DesktopStatus> {
        match slot {
            HotkeySlot::Main => &self.status,
            HotkeySlot::Panel => &self.panel_status,
        }
    }

    fn slot_status_value(&self, slot: HotkeySlot) -> DesktopStatus {
        self.slot_status(slot)
            .lock()
            .map(|status| status.clone())
            .unwrap_or_else(|_| DesktopStatus::unavailable(DEFAULT_PANEL_HOTKEY))
    }

    /// Resolve which slot owns a pressed shortcut, so the global-shortcut
    /// handler can dispatch to the matching surface. The handler receives the
    /// normalized `Shortcut` display form, while stored config keeps the raw
    /// (trimmed) text, so compare via parsing when strings differ.
    pub fn hotkey_owner(&self, shortcut: &str) -> Option<HotkeySlot> {
        let main = self.status.lock().ok()?;
        if main.hotkey_active && same_shortcut(&main.hotkey, shortcut) {
            return Some(HotkeySlot::Main);
        }
        drop(main);
        let panel = self.panel_status.lock().ok()?;
        if panel.hotkey_active && same_shortcut(&panel.hotkey, shortcut) {
            return Some(HotkeySlot::Panel);
        }
        None
    }

    /// The hotkey registered by the other slot; used to reject duplicates.
    fn conflicting_hotkey(&self, slot: HotkeySlot) -> Option<String> {
        let other = self.slot_status(match slot {
            HotkeySlot::Main => HotkeySlot::Panel,
            HotkeySlot::Panel => HotkeySlot::Main,
        });
        let status = other.lock().ok()?;
        status.hotkey_active.then(|| status.hotkey.clone())
    }

    pub fn mark_tray_available(&self) {
        self.tray_available.store(true, Ordering::Release);
    }

    pub fn tray_available(&self) -> bool {
        self.tray_available.load(Ordering::Acquire)
    }
}

trait ShortcutRegistrar {
    fn register(&self, hotkey: &str) -> Result<(), ()>;
    fn unregister(&self, hotkey: &str) -> Result<(), ()>;
}

struct TauriShortcutRegistrar<'a, R: Runtime>(&'a AppHandle<R>);

impl<R: Runtime> ShortcutRegistrar for TauriShortcutRegistrar<'_, R> {
    fn register(&self, hotkey: &str) -> Result<(), ()> {
        self.0.global_shortcut().register(hotkey).map_err(|_| ())
    }

    fn unregister(&self, hotkey: &str) -> Result<(), ()> {
        self.0.global_shortcut().unregister(hotkey).map_err(|_| ())
    }
}

pub fn register_hotkey<R: Runtime>(
    app: &AppHandle<R>,
    state: &DesktopState,
    requested: &str,
) -> Result<DesktopStatus, &'static str> {
    register_hotkey_in_slot(app, state, HotkeySlot::Main, requested)
}

pub fn register_panel_hotkey<R: Runtime>(
    app: &AppHandle<R>,
    state: &DesktopState,
    requested: &str,
) -> Result<DesktopStatus, &'static str> {
    register_hotkey_in_slot(app, state, HotkeySlot::Panel, requested)
}

fn register_hotkey_in_slot<R: Runtime>(
    app: &AppHandle<R>,
    state: &DesktopState,
    slot: HotkeySlot,
    requested: &str,
) -> Result<DesktopStatus, &'static str> {
    replace_hotkey_in_slot_with(&TauriShortcutRegistrar(app), state, slot, requested, || {
        Ok(())
    })
    .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE)?;
    Ok(state.slot_status_value(slot))
}

fn validated_hotkey(value: &str) -> Result<String, &'static str> {
    let normalized = value.trim();
    if normalized.is_empty() || normalized.len() > 64 {
        return Err(HOTKEY_UNAVAILABLE_MESSAGE);
    }
    let shortcut = normalized
        .parse::<Shortcut>()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE)?;
    if shortcut.mods.is_empty() {
        return Err(HOTKEY_UNAVAILABLE_MESSAGE);
    }
    Ok(normalized.to_string())
}

#[cfg(test)]
fn replace_hotkey_and_persist_with<B, T, F>(
    backend: &B,
    state: &DesktopState,
    requested: &str,
    persist: F,
) -> Result<T, String>
where
    B: ShortcutRegistrar,
    F: FnOnce() -> Result<T, String>,
{
    replace_hotkey_in_slot_with(backend, state, HotkeySlot::Main, requested, persist)
}

#[cfg(test)]
fn replace_panel_hotkey_and_persist_with<B, T, F>(
    backend: &B,
    state: &DesktopState,
    requested: &str,
    persist: F,
) -> Result<T, String>
where
    B: ShortcutRegistrar,
    F: FnOnce() -> Result<T, String>,
{
    replace_hotkey_in_slot_with(backend, state, HotkeySlot::Panel, requested, persist)
}

/// Replace both hotkeys inside one transaction: register both new keys,
/// persist once, then unregister the old keys. Any failure rolls both slots
/// back to their previous registration.
pub fn replace_hotkeys_and_persist<R, T, F>(
    app: &AppHandle<R>,
    state: &DesktopState,
    main_requested: &str,
    panel_requested: &str,
    persist: F,
) -> Result<T, String>
where
    R: Runtime,
    F: FnOnce() -> Result<T, String>,
{
    replace_hotkeys_with(
        &TauriShortcutRegistrar(app),
        state,
        main_requested,
        panel_requested,
        persist,
    )
}

fn replace_hotkeys_with<B, T, F>(
    backend: &B,
    state: &DesktopState,
    main_requested: &str,
    panel_requested: &str,
    persist: F,
) -> Result<T, String>
where
    B: ShortcutRegistrar,
    F: FnOnce() -> Result<T, String>,
{
    let _transaction = state
        .transaction
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    let mut pending_cleanup = state
        .pending_cleanup
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    pending_cleanup.retain(|hotkey| backend.unregister(hotkey).is_err());

    let main_requested = validated_hotkey(main_requested).map_err(str::to_string)?;
    let panel_requested = validated_hotkey(panel_requested).map_err(str::to_string)?;
    if main_requested == panel_requested {
        return Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
    }

    let mut main_current = state
        .status
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    let mut panel_current = state
        .panel_status
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    let main_previous = main_current.clone();
    let panel_previous = panel_current.clone();

    let main_needs_register =
        !(main_previous.hotkey_active && main_previous.hotkey == main_requested);
    let panel_needs_register =
        !(panel_previous.hotkey_active && panel_previous.hotkey == panel_requested);

    if main_needs_register && backend.register(&main_requested).is_err() {
        if main_previous.hotkey_active {
            *main_current = main_previous;
            main_current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
        } else {
            *main_current = DesktopStatus::unavailable(main_requested);
        }
        return Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
    }
    if panel_needs_register && backend.register(&panel_requested).is_err() {
        rollback_registration(
            backend,
            pending_cleanup.as_mut(),
            main_needs_register,
            &main_requested,
        );
        *main_current = main_previous;
        if panel_previous.hotkey_active {
            *panel_current = panel_previous;
            panel_current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
        } else {
            *panel_current = DesktopStatus::unavailable(panel_requested);
        }
        return Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
    }

    match persist() {
        Ok(saved) => {
            if main_previous.hotkey_active && main_previous.hotkey != main_requested {
                let failed = backend.unregister(&main_previous.hotkey).is_err();
                if failed && !pending_cleanup.contains(&main_previous.hotkey) {
                    pending_cleanup.push(main_previous.hotkey.clone());
                }
            }
            if panel_previous.hotkey_active && panel_previous.hotkey != panel_requested {
                let failed = backend.unregister(&panel_previous.hotkey).is_err();
                if failed && !pending_cleanup.contains(&panel_previous.hotkey) {
                    pending_cleanup.push(panel_previous.hotkey.clone());
                }
            }
            *main_current = DesktopStatus::active(main_requested);
            *panel_current = DesktopStatus::active(panel_requested);
            if !pending_cleanup.is_empty() {
                main_current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
                panel_current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
            }
            Ok(saved)
        }
        Err(error) => {
            rollback_registration(
                backend,
                pending_cleanup.as_mut(),
                main_needs_register,
                &main_requested,
            );
            rollback_registration(
                backend,
                pending_cleanup.as_mut(),
                panel_needs_register,
                &panel_requested,
            );
            *main_current = main_previous;
            *panel_current = panel_previous;
            Err(error)
        }
    }
}

fn rollback_registration(
    backend: &impl ShortcutRegistrar,
    pending_cleanup: &mut Vec<String>,
    registered: bool,
    requested: &str,
) {
    if !registered {
        return;
    }
    if backend.unregister(requested).is_err()
        && !pending_cleanup.iter().any(|hotkey| hotkey == requested)
    {
        pending_cleanup.push(requested.to_string());
    }
}

fn replace_hotkey_in_slot_with<B, T, F>(
    backend: &B,
    state: &DesktopState,
    slot: HotkeySlot,
    requested: &str,
    persist: F,
) -> Result<T, String>
where
    B: ShortcutRegistrar,
    F: FnOnce() -> Result<T, String>,
{
    let _transaction = state
        .transaction
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    let mut pending_cleanup = state
        .pending_cleanup
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    pending_cleanup.retain(|hotkey| backend.unregister(hotkey).is_err());
    let requested = validated_hotkey(requested).map_err(str::to_string)?;
    // Checked before taking this slot's lock so two concurrent replacements
    // can never lock both slots in opposite order; the transaction lock
    // already serializes every replacement.
    if state.conflicting_hotkey(slot).as_deref() == Some(requested.as_str()) {
        return Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
    }
    let mut current = state
        .slot_status(slot)
        .lock()
        .map_err(|_| HOTKEY_UNAVAILABLE_MESSAGE.to_string())?;
    let previous = current.clone();

    if previous.hotkey_active && previous.hotkey == requested {
        let saved = persist()?;
        current.message =
            (!pending_cleanup.is_empty()).then(|| HOTKEY_UNAVAILABLE_MESSAGE.to_string());
        return Ok(saved);
    }

    if backend.register(&requested).is_err() {
        if previous.hotkey_active {
            *current = previous;
            current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
        } else {
            *current = DesktopStatus::unavailable(requested);
        }
        return Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
    }

    match persist() {
        Ok(saved) => {
            let cleanup_failed = previous.hotkey_active
                && previous.hotkey != requested
                && backend.unregister(&previous.hotkey).is_err();
            if cleanup_failed && !pending_cleanup.contains(&previous.hotkey) {
                pending_cleanup.push(previous.hotkey.clone());
            }
            *current = DesktopStatus::active(requested);
            if !pending_cleanup.is_empty() {
                current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
            }
            Ok(saved)
        }
        Err(error) => {
            let cleanup_failed = backend.unregister(&requested).is_err();
            if cleanup_failed && !pending_cleanup.contains(&requested) {
                pending_cleanup.push(requested.clone());
            }
            *current = previous;
            if !pending_cleanup.is_empty() {
                current.message = Some(HOTKEY_UNAVAILABLE_MESSAGE.to_string());
            }
            Err(error)
        }
    }
}

#[derive(Clone, Serialize)]
struct HostActionPayload {
    action: &'static str,
}

pub fn setup_tray(app: &mut App) -> tauri::Result<()> {
    let open = menu_item(app, HostAction::Open, "打开 Reflex")?;
    let panel = menu_item(app, HostAction::Panel, "快捷面板")?;
    let recent = menu_item(app, HostAction::Recent, "最近结果")?;
    let history = menu_item(app, HostAction::History, "历史记录")?;
    let plugins = menu_item(app, HostAction::Plugins, "插件")?;
    let settings = menu_item(app, HostAction::Settings, "设置")?;
    let quit = menu_item(app, HostAction::Quit, "退出")?;
    let menu = Menu::with_items(
        app,
        &[&open, &panel, &recent, &history, &plugins, &settings, &quit],
    )?;

    let mut builder = TrayIconBuilder::with_id("reflex-main")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .tooltip("Reflex")
        .on_menu_event(|app, event| match event.id().as_ref() {
            "open" => dispatch_host_action(app, HostAction::Open),
            "panel" => dispatch_host_action(app, HostAction::Panel),
            "recent" => dispatch_host_action(app, HostAction::Recent),
            "history" => dispatch_host_action(app, HostAction::History),
            "plugins" => dispatch_host_action(app, HostAction::Plugins),
            "settings" => dispatch_host_action(app, HostAction::Settings),
            "quit" => dispatch_host_action(app, HostAction::Quit),
            _ => {}
        })
        .on_tray_icon_event(|tray, event| {
            if matches!(
                event,
                TrayIconEvent::Click {
                    button: MouseButton::Left,
                    button_state: MouseButtonState::Up,
                    ..
                }
            ) {
                dispatch_host_action(tray.app_handle(), HostAction::Open);
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;
    Ok(())
}

fn menu_item(app: &App, action: HostAction, label: &str) -> tauri::Result<MenuItem<tauri::Wry>> {
    MenuItem::with_id(app, action.as_str(), label, true, None::<&str>)
}

fn same_shortcut(stored: &str, pressed: &str) -> bool {
    if stored == pressed {
        return true;
    }
    match (stored.parse::<Shortcut>(), pressed.parse::<Shortcut>()) {
        (Ok(left), Ok(right)) => left == right,
        _ => false,
    }
}

fn dispatch_host_action(app: &AppHandle, action: HostAction) {
    if action == HostAction::Quit {
        app.exit(0);
        return;
    }
    // 历史记录：主窗口内的视图（与 CC Switch 同构），不再单独开窗
    if action == HostAction::Panel {
        let _ = toggle_panel_window(app);
        return;
    }
    let _ = show_main_window(app);
    if action != HostAction::Open {
        let _ = app.emit(
            HOST_ACTION_EVENT,
            HostActionPayload {
                action: action.as_str(),
            },
        );
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;
    use std::sync::{mpsc, Arc};
    use std::thread;
    use std::time::Duration;

    use super::{
        replace_hotkey_and_persist_with, validated_hotkey, DesktopState, DesktopStatus, HostAction,
        ShortcutRegistrar, HOTKEY_UNAVAILABLE_MESSAGE,
    };

    struct FakeRegistrar {
        calls: Mutex<Vec<String>>,
        fail_registration: Option<&'static str>,
        fail_unregistration: Mutex<Option<&'static str>>,
    }

    impl FakeRegistrar {
        fn recording(fail_registration: Option<&'static str>) -> Self {
            Self {
                calls: Mutex::new(Vec::new()),
                fail_registration,
                fail_unregistration: Mutex::new(None),
            }
        }

        fn failing_unregistration(hotkey: &'static str) -> Self {
            Self {
                calls: Mutex::new(Vec::new()),
                fail_registration: None,
                fail_unregistration: Mutex::new(Some(hotkey)),
            }
        }

        fn calls(&self) -> Vec<String> {
            self.calls.lock().unwrap().clone()
        }

        fn record(&self, call: &str) {
            self.calls.lock().unwrap().push(call.to_string());
        }
    }

    impl ShortcutRegistrar for FakeRegistrar {
        fn register(&self, hotkey: &str) -> Result<(), ()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("register:{hotkey}"));
            if self.fail_registration == Some(hotkey) {
                Err(())
            } else {
                Ok(())
            }
        }

        fn unregister(&self, hotkey: &str) -> Result<(), ()> {
            self.calls
                .lock()
                .unwrap()
                .push(format!("unregister:{hotkey}"));
            let mut failure = self.fail_unregistration.lock().unwrap();
            if *failure == Some(hotkey) {
                *failure = None;
                Err(())
            } else {
                Ok(())
            }
        }
    }

    #[test]
    fn host_actions_use_stable_wire_ids() {
        assert_eq!(HostAction::Open.as_str(), "open");
        assert_eq!(HostAction::Recent.as_str(), "recent");
        assert_eq!(HostAction::Plugins.as_str(), "plugins");
        assert_eq!(HostAction::Settings.as_str(), "settings");
        assert_eq!(HostAction::Quit.as_str(), "quit");
        assert_eq!(HostAction::History.as_str(), "history");
        assert_eq!(HostAction::Panel.as_str(), "panel");
    }

    #[test]
    fn hotkey_owner_resolves_each_registered_slot() {
        let state = DesktopState::new_with_panel("Ctrl+Alt+R", "Alt+Q");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");
        *state.panel_status.lock().unwrap() = DesktopStatus::active("Alt+Q");

        assert_eq!(
            state.hotkey_owner("Ctrl+Alt+R"),
            Some(super::HotkeySlot::Main)
        );
        assert_eq!(state.hotkey_owner("Alt+Q"), Some(super::HotkeySlot::Panel));
        assert_eq!(state.hotkey_owner("Ctrl+Shift+Z"), None);
    }

    #[test]
    fn panel_hotkey_cannot_duplicate_an_active_main_hotkey() {
        let backend = FakeRegistrar::recording(None);
        let state = DesktopState::new_with_panel("Ctrl+Alt+R", "Alt+Q");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");
        *state.panel_status.lock().unwrap() = DesktopStatus::active("Alt+Q");

        let result =
            super::replace_panel_hotkey_and_persist_with(&backend, &state, "Ctrl+Alt+R", || {
                backend.record("persist");
                Ok(())
            });

        assert_eq!(result, Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string()));
        assert_eq!(state.panel_status(), DesktopStatus::active("Alt+Q"));
        assert!(!backend.calls().contains(&"persist".to_string()));
    }

    #[test]
    fn panel_hotkey_replacement_persists_and_swaps_independently() {
        let backend = FakeRegistrar::recording(None);
        let state = DesktopState::new_with_panel("Ctrl+Alt+R", "Alt+Q");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");
        *state.panel_status.lock().unwrap() = DesktopStatus::active("Alt+Q");

        let saved =
            super::replace_panel_hotkey_and_persist_with(&backend, &state, "Ctrl+Shift+P", || {
                backend.record("persist");
                Ok("saved")
            })
            .unwrap();

        assert_eq!(saved, "saved");
        let panel = state.panel_status();
        assert_eq!(panel.hotkey, "Ctrl+Shift+P");
        assert!(panel.hotkey_active);
        let main = state.status();
        assert_eq!(main.hotkey, "Ctrl+Alt+R");
        assert!(main.hotkey_active);
        assert_eq!(
            backend.calls(),
            vec!["register:Ctrl+Shift+P", "persist", "unregister:Alt+Q"]
        );
    }

    #[test]
    fn desktop_status_never_contains_a_backend_error() {
        let status = DesktopStatus::unavailable("Ctrl+Alt+R");
        let serialized = serde_json::to_value(status).unwrap();

        assert_eq!(serialized["hotkey"], "Ctrl+Alt+R");
        assert_eq!(serialized["hotkey_active"], false);
        assert_eq!(serialized["message"], HOTKEY_UNAVAILABLE_MESSAGE);
        assert!(!serialized.to_string().contains("RegisterHotKey failed"));
    }

    #[test]
    fn desktop_state_only_allows_close_to_tray_after_tray_setup() {
        let state = DesktopState::new("Ctrl+Alt+R");

        assert!(!state.tray_available());
        state.mark_tray_available();
        assert!(state.tray_available());
    }

    #[test]
    fn hotkey_validation_requires_a_bounded_modified_key() {
        assert_eq!(validated_hotkey("Ctrl+Alt+R"), Ok("Ctrl+Alt+R".to_string()));
        assert_eq!(
            validated_hotkey("  Ctrl+Shift+K  "),
            Ok("Ctrl+Shift+K".to_string())
        );
        assert_eq!(validated_hotkey("R"), Err(HOTKEY_UNAVAILABLE_MESSAGE));
        assert_eq!(validated_hotkey(""), Err(HOTKEY_UNAVAILABLE_MESSAGE));
        assert_eq!(
            validated_hotkey(&format!("Ctrl+{}", "X".repeat(80))),
            Err(HOTKEY_UNAVAILABLE_MESSAGE)
        );
    }

    #[test]
    fn hotkey_conflict_keeps_the_previous_registration_and_skips_persistence() {
        let backend = FakeRegistrar::recording(Some("Ctrl+Shift+K"));
        let state = DesktopState::new("Ctrl+Alt+R");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");

        let result = replace_hotkey_and_persist_with(&backend, &state, "Ctrl+Shift+K", || {
            backend.record("persist");
            Ok(())
        });

        assert_eq!(result, Err(HOTKEY_UNAVAILABLE_MESSAGE.to_string()));
        let status = state.status();
        assert_eq!(status.hotkey, "Ctrl+Alt+R");
        assert!(status.hotkey_active);
        assert_eq!(status.message.as_deref(), Some(HOTKEY_UNAVAILABLE_MESSAGE));
        assert_eq!(backend.calls(), vec!["register:Ctrl+Shift+K"]);
    }

    #[test]
    fn persisted_replacement_registers_new_before_saving_and_unregisters_old_afterward() {
        let backend = FakeRegistrar::recording(None);
        let state = DesktopState::new("Ctrl+Alt+R");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");

        let saved = replace_hotkey_and_persist_with(&backend, &state, "Ctrl+Shift+K", || {
            backend.record("persist");
            Ok("saved")
        })
        .unwrap();

        assert_eq!(saved, "saved");
        assert_eq!(state.status(), DesktopStatus::active("Ctrl+Shift+K"));
        assert_eq!(
            backend.calls(),
            vec!["register:Ctrl+Shift+K", "persist", "unregister:Ctrl+Alt+R"]
        );
    }

    #[test]
    fn persistence_failure_unregisters_only_the_new_hotkey() {
        let backend = FakeRegistrar::recording(None);
        let state = DesktopState::new("Ctrl+Alt+R");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");

        let result = replace_hotkey_and_persist_with(&backend, &state, "Ctrl+Shift+K", || {
            backend.record("persist");
            Err::<(), _>("配置存储暂不可用。".to_string())
        });

        assert_eq!(result, Err("配置存储暂不可用。".to_string()));
        assert_eq!(state.status(), DesktopStatus::active("Ctrl+Alt+R"));
        assert_eq!(
            backend.calls(),
            vec![
                "register:Ctrl+Shift+K",
                "persist",
                "unregister:Ctrl+Shift+K"
            ]
        );
    }

    #[test]
    fn rollback_cleanup_failure_keeps_the_old_hotkey_and_marks_degraded_status() {
        let backend = FakeRegistrar::failing_unregistration("Ctrl+Shift+K");
        let state = DesktopState::new("Ctrl+Alt+R");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");

        let result = replace_hotkey_and_persist_with(&backend, &state, "Ctrl+Shift+K", || {
            Err::<(), _>("配置存储暂不可用。".to_string())
        });

        assert_eq!(result, Err("配置存储暂不可用。".to_string()));
        let status = state.status();
        assert_eq!(status.hotkey, "Ctrl+Alt+R");
        assert!(status.hotkey_active);
        assert_eq!(status.message.as_deref(), Some(HOTKEY_UNAVAILABLE_MESSAGE));
        assert_eq!(
            backend.calls(),
            vec!["register:Ctrl+Shift+K", "unregister:Ctrl+Shift+K"]
        );
    }

    #[test]
    fn next_transaction_retries_and_clears_a_pending_hotkey_cleanup() {
        let backend = FakeRegistrar::failing_unregistration("Ctrl+Shift+K");
        let state = DesktopState::new("Ctrl+Alt+R");
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");

        replace_hotkey_and_persist_with(&backend, &state, "Ctrl+Shift+K", || {
            Err::<(), _>("配置存储暂不可用。".to_string())
        })
        .unwrap_err();

        replace_hotkey_and_persist_with(&backend, &state, "Ctrl+Alt+R", || Ok(())).unwrap();

        assert_eq!(state.status(), DesktopStatus::active("Ctrl+Alt+R"));
        assert_eq!(
            backend.calls(),
            vec![
                "register:Ctrl+Shift+K",
                "unregister:Ctrl+Shift+K",
                "unregister:Ctrl+Shift+K"
            ]
        );
    }

    #[test]
    fn concurrent_persistence_transactions_are_serialized() {
        let backend = Arc::new(FakeRegistrar::recording(None));
        let state = Arc::new(DesktopState::new("Ctrl+Alt+R"));
        *state.status.lock().unwrap() = DesktopStatus::active("Ctrl+Alt+R");
        let (first_entered_tx, first_entered_rx) = mpsc::channel();
        let (release_first_tx, release_first_rx) = mpsc::channel();
        let (second_entered_tx, second_entered_rx) = mpsc::channel();

        let first_backend = backend.clone();
        let first_state = state.clone();
        let first = thread::spawn(move || {
            replace_hotkey_and_persist_with(
                first_backend.as_ref(),
                first_state.as_ref(),
                "Ctrl+Shift+K",
                || {
                    first_entered_tx.send(()).unwrap();
                    release_first_rx.recv().unwrap();
                    Ok(())
                },
            )
        });
        first_entered_rx.recv().unwrap();

        let second_backend = backend.clone();
        let second_state = state.clone();
        let second = thread::spawn(move || {
            replace_hotkey_and_persist_with(
                second_backend.as_ref(),
                second_state.as_ref(),
                "Ctrl+Alt+M",
                || {
                    second_entered_tx.send(()).unwrap();
                    Ok(())
                },
            )
        });

        assert!(second_entered_rx
            .recv_timeout(Duration::from_millis(100))
            .is_err());
        release_first_tx.send(()).unwrap();
        first.join().unwrap().unwrap();
        second.join().unwrap().unwrap();
        second_entered_rx.recv().unwrap();
        assert_eq!(state.status(), DesktopStatus::active("Ctrl+Alt+M"));
    }
}
