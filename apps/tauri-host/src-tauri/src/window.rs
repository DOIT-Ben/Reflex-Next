use tauri::{
    plugin::{Builder as PluginBuilder, TauriPlugin},
    webview::NewWindowResponse,
    AppHandle, Manager, PhysicalPosition, Runtime, Url, WebviewUrl, WebviewWindowBuilder,
};

const MIN_VISIBLE_EDGE: i64 = 64;
pub const HISTORY_WINDOW_LABEL: &str = "history";
const HISTORY_WINDOW_TITLE: &str = "Reflex - 历史记录";
const HISTORY_DEFAULT_SIZE: (f64, f64) = (1040.0, 720.0);
const HISTORY_MINIMUM_SIZE: (f64, f64) = (760.0, 560.0);
pub const PANEL_WINDOW_LABEL: &str = "panel";
const PANEL_WINDOW_TITLE: &str = "Reflex 快捷面板";
const PANEL_DEFAULT_SIZE: (f64, f64) = (680.0, 460.0);
pub const WINDOW_UNAVAILABLE_MESSAGE: &str = "窗口暂时无法打开，请从托盘重试。";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PhysicalBounds {
    x: i32,
    y: i32,
    width: i32,
    height: i32,
}

impl PhysicalBounds {
    pub const fn new(x: i32, y: i32, width: i32, height: i32) -> Self {
        Self {
            x,
            y,
            width,
            height,
        }
    }

    fn right(self) -> i64 {
        i64::from(self.x) + i64::from(self.width.max(0))
    }

    fn bottom(self) -> i64 {
        i64::from(self.y) + i64::from(self.height.max(0))
    }
}

pub fn recover_window_position(
    window: PhysicalBounds,
    work_areas: &[PhysicalBounds],
    fallback: PhysicalBounds,
) -> Option<(i32, i32)> {
    if work_areas
        .iter()
        .copied()
        .any(|work_area| sufficiently_visible(window, work_area))
    {
        return None;
    }

    let horizontal_space = (fallback.width - window.width).max(0);
    let vertical_space = (fallback.height - window.height).max(0);
    Some((
        fallback.x + horizontal_space / 2,
        fallback.y + vertical_space / 2,
    ))
}

fn sufficiently_visible(window: PhysicalBounds, work_area: PhysicalBounds) -> bool {
    let visible_width = window
        .right()
        .min(work_area.right())
        .saturating_sub(i64::from(window.x.max(work_area.x)));
    let visible_height = window
        .bottom()
        .min(work_area.bottom())
        .saturating_sub(i64::from(window.y.max(work_area.y)));
    visible_width >= MIN_VISIBLE_EDGE && visible_height >= MIN_VISIBLE_EDGE
}

pub fn show_main_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    let window = app
        .get_webview_window("main")
        .ok_or(WINDOW_UNAVAILABLE_MESSAGE)?;
    recover_main_window_position(&window);
    // SW_SHOW alone leaves an iconic window iconic, so restore after show.
    window.show().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }
    window.set_focus().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

pub fn history_window_url() -> &'static str {
    "index.html?view=history"
}

pub fn panel_window_url() -> &'static str {
    "index.html?view=panel"
}

pub fn navigation_guard<R: Runtime>() -> TauriPlugin<R> {
    PluginBuilder::new("navigation-guard")
        .on_navigation(|webview, url| navigation_is_allowed(webview.label(), url))
        .build()
}

pub fn show_history_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    if let Some(window) = app.get_webview_window(HISTORY_WINDOW_LABEL) {
        recover_window_position_for(&window);
        window.show().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
        if window.is_minimized().unwrap_or(false) {
            let _ = window.unminimize();
        }
        return window.set_focus().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE);
    }

    WebviewWindowBuilder::new(
        app,
        HISTORY_WINDOW_LABEL,
        WebviewUrl::App(history_window_url().into()),
    )
    .title(HISTORY_WINDOW_TITLE)
    .inner_size(HISTORY_DEFAULT_SIZE.0, HISTORY_DEFAULT_SIZE.1)
    .min_inner_size(HISTORY_MINIMUM_SIZE.0, HISTORY_MINIMUM_SIZE.1)
    .on_navigation(is_local_history_url)
    .on_new_window(|_, _| NewWindowResponse::Deny)
    .build()
    .map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
    Ok(())
}

pub fn reuse_intent_is_valid(kind: &str, history_id: &str) -> bool {
    matches!(kind, "input" | "result")
        && !history_id.is_empty()
        && history_id.len() <= 128
        && history_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

/// Create the hidden quick panel once at startup so toggling it later only
/// pays show/focus cost. Existing windows are kept as-is.
pub fn ensure_panel_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    if app.get_webview_window(PANEL_WINDOW_LABEL).is_some() {
        return Ok(());
    }
    WebviewWindowBuilder::new(
        app,
        PANEL_WINDOW_LABEL,
        WebviewUrl::App(panel_window_url().into()),
    )
    .title(PANEL_WINDOW_TITLE)
    .inner_size(PANEL_DEFAULT_SIZE.0, PANEL_DEFAULT_SIZE.1)
    .resizable(false)
    .maximizable(false)
    .minimizable(false)
    .visible(false)
    .decorations(false)
    .transparent(true)
    .always_on_top(true)
    .skip_taskbar(true)
    .on_navigation(is_local_panel_url)
    .on_new_window(|_, _| NewWindowResponse::Deny)
    .build()
    .map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
    Ok(())
}

pub fn show_panel_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    ensure_panel_window(app)?;
    let window = app
        .get_webview_window(PANEL_WINDOW_LABEL)
        .ok_or(WINDOW_UNAVAILABLE_MESSAGE)?;
    position_panel_window(&window);
    window.show().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }
    window.set_focus().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

pub fn hide_panel_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    app.get_webview_window(PANEL_WINDOW_LABEL)
        .ok_or(WINDOW_UNAVAILABLE_MESSAGE)?
        .hide()
        .map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

pub fn toggle_panel_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    ensure_panel_window(app)?;
    let window = app
        .get_webview_window(PANEL_WINDOW_LABEL)
        .ok_or(WINDOW_UNAVAILABLE_MESSAGE)?;
    if window.is_visible().unwrap_or(false) {
        return hide_panel_window(app);
    }
    position_panel_window(&window);
    window.show().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }
    window.set_focus().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

/// Place the panel near the top-center of the monitor that hosts the cursor,
/// falling back to the current/first monitor when the cursor is unavailable.
fn position_panel_window<R: Runtime>(window: &tauri::WebviewWindow<R>) {
    let Ok(size) = window.outer_size() else {
        return;
    };
    let app = window.app_handle();
    let cursor = app.cursor_position().ok();
    let monitors = window.available_monitors().unwrap_or_default();
    let target = cursor
        .and_then(|cursor| {
            let cursor_x = cursor.x;
            let cursor_y = cursor.y;
            monitors
                .iter()
                .find(|monitor| {
                    let position = monitor.position();
                    let size = monitor.size();
                    let contains_x = cursor_x >= f64::from(position.x)
                        && cursor_x < f64::from(position.x + size.width as i32);
                    let contains_y = cursor_y >= f64::from(position.y)
                        && cursor_y < f64::from(position.y + size.height as i32);
                    contains_x && contains_y
                })
                .cloned()
        })
        .or_else(|| window.current_monitor().ok().flatten())
        .or_else(|| monitors.first().cloned());
    let Some(monitor) = target else {
        return;
    };
    let (x, y) = panel_position_for_work_area(
        bounds_from_rect(monitor.work_area()),
        i32::try_from(size.width).unwrap_or(i32::MAX),
        i32::try_from(size.height).unwrap_or(i32::MAX),
    );
    let _ = window.set_position(PhysicalPosition::new(x, y));
}

/// Pure placement rule: horizontally centered, about 12% down the work area,
/// clamped so the panel never leaves its monitor.
pub fn panel_position_for_work_area(
    work_area: PhysicalBounds,
    panel_width: i32,
    panel_height: i32,
) -> (i32, i32) {
    let horizontal_space = (i64::from(work_area.width) - i64::from(panel_width)).max(0);
    let vertical_offset = (i64::from(work_area.height) / 8).max(48);
    let vertical_space = (i64::from(work_area.height) - i64::from(panel_height)).max(0);
    let x = i64::from(work_area.x) + horizontal_space / 2;
    let y = i64::from(work_area.y) + vertical_offset.min(vertical_space);
    (x as i32, y as i32)
}

pub fn hide_main_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    app.get_webview_window("main")
        .ok_or(WINDOW_UNAVAILABLE_MESSAGE)?
        .hide()
        .map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

fn recover_main_window_position<R: Runtime>(window: &tauri::WebviewWindow<R>) {
    recover_window_position_for(window);
}

fn recover_window_position_for<R: Runtime>(window: &tauri::WebviewWindow<R>) {
    let Ok(position) = window.outer_position() else {
        return;
    };
    let Ok(size) = window.outer_size() else {
        return;
    };
    let Ok(monitors) = window.available_monitors() else {
        return;
    };
    let work_areas = monitors
        .iter()
        .map(|monitor| bounds_from_rect(monitor.work_area()))
        .collect::<Vec<_>>();
    let fallback = window
        .current_monitor()
        .ok()
        .flatten()
        .or_else(|| window.primary_monitor().ok().flatten())
        .or_else(|| monitors.first().cloned());
    let Some(fallback) = fallback else {
        return;
    };
    let window_bounds = PhysicalBounds::new(
        position.x,
        position.y,
        i32::try_from(size.width).unwrap_or(i32::MAX),
        i32::try_from(size.height).unwrap_or(i32::MAX),
    );
    if let Some((x, y)) = recover_window_position(
        window_bounds,
        &work_areas,
        bounds_from_rect(fallback.work_area()),
    ) {
        let _ = window.set_position(PhysicalPosition::new(x, y));
    }
}

fn is_local_history_url(url: &Url) -> bool {
    navigation_is_allowed_for_environment(HISTORY_WINDOW_LABEL, url, cfg!(debug_assertions))
}

fn is_local_panel_url(url: &Url) -> bool {
    navigation_is_allowed_for_environment(PANEL_WINDOW_LABEL, url, cfg!(debug_assertions))
}

fn navigation_is_allowed(window_label: &str, url: &Url) -> bool {
    navigation_is_allowed_for_environment(window_label, url, cfg!(debug_assertions))
}

fn navigation_is_allowed_for_environment(
    window_label: &str,
    url: &Url,
    allow_dev_server: bool,
) -> bool {
    match window_label {
        "main" => {
            is_trusted_local_origin(url, allow_dev_server)
                && matches!(url.path(), "/" | "/index.html")
                && url.query().is_none()
        }
        HISTORY_WINDOW_LABEL => {
            is_trusted_local_origin(url, allow_dev_server)
                && url.path() == "/index.html"
                && url.query() == Some("view=history")
        }
        PANEL_WINDOW_LABEL => {
            is_trusted_local_origin(url, allow_dev_server)
                && url.path() == "/index.html"
                && url.query() == Some("view=panel")
        }
        _ => false,
    }
}

fn is_trusted_local_origin(url: &Url, allow_dev_server: bool) -> bool {
    url.username().is_empty()
        && url.password().is_none()
        && (matches!(
            (url.scheme(), url.host_str(), url.port()),
            ("tauri", Some("localhost"), None) | ("http" | "https", Some("tauri.localhost"), None)
        ) || (allow_dev_server
            && matches!(
                (url.scheme(), url.host_str(), url.port()),
                ("http", Some("127.0.0.1"), Some(1420))
            )))
}

fn bounds_from_rect(rect: &tauri::PhysicalRect<i32, u32>) -> PhysicalBounds {
    PhysicalBounds::new(
        rect.position.x,
        rect.position.y,
        i32::try_from(rect.size.width).unwrap_or(i32::MAX),
        i32::try_from(rect.size.height).unwrap_or(i32::MAX),
    )
}

#[cfg(test)]
mod tests {
    use super::{
        history_window_url, is_local_history_url, navigation_is_allowed,
        navigation_is_allowed_for_environment, panel_position_for_work_area, panel_window_url,
        recover_window_position, reuse_intent_is_valid, PhysicalBounds, HISTORY_DEFAULT_SIZE,
        HISTORY_MINIMUM_SIZE, PANEL_DEFAULT_SIZE,
    };

    const PRIMARY: PhysicalBounds = PhysicalBounds::new(0, 0, 1920, 1040);
    const LEFT: PhysicalBounds = PhysicalBounds::new(-1920, 0, 1920, 1040);

    #[test]
    fn keeps_a_window_that_is_visible_on_a_negative_coordinate_monitor() {
        let window = PhysicalBounds::new(-1800, 120, 760, 540);

        assert_eq!(
            recover_window_position(window, &[PRIMARY, LEFT], PRIMARY),
            None
        );
    }

    #[test]
    fn recenters_a_fully_offscreen_window_in_the_fallback_work_area() {
        let window = PhysicalBounds::new(5000, 3000, 760, 540);

        assert_eq!(
            recover_window_position(window, &[PRIMARY, LEFT], PRIMARY),
            Some((580, 250))
        );
    }

    #[test]
    fn recenters_when_less_than_the_minimum_corner_is_visible() {
        let window = PhysicalBounds::new(1888, 1000, 760, 540);

        assert_eq!(
            recover_window_position(window, &[PRIMARY, LEFT], PRIMARY),
            Some((580, 250))
        );
    }

    #[test]
    fn pins_an_oversized_window_to_the_fallback_origin() {
        let window = PhysicalBounds::new(4000, 2000, 2400, 1400);

        assert_eq!(
            recover_window_position(window, &[PRIMARY], PRIMARY),
            Some((0, 0))
        );
    }

    #[test]
    fn history_window_uses_a_fixed_local_view_query() {
        assert_eq!(history_window_url(), "index.html?view=history");
        assert_eq!(HISTORY_DEFAULT_SIZE, (1040.0, 720.0));
        assert_eq!(HISTORY_MINIMUM_SIZE, (760.0, 560.0));
    }

    #[test]
    fn panel_window_uses_a_fixed_local_view_query() {
        assert_eq!(panel_window_url(), "index.html?view=panel");
        assert_eq!(PANEL_DEFAULT_SIZE, (680.0, 460.0));
    }

    #[test]
    fn panel_navigation_allows_only_the_fixed_local_entry() {
        for url in [
            "tauri://localhost/index.html?view=panel",
            "http://tauri.localhost/index.html?view=panel",
            "http://127.0.0.1:1420/index.html?view=panel",
        ] {
            assert!(
                navigation_is_allowed("panel", &url.parse().unwrap()),
                "expected allow: {url}"
            );
        }
        for url in [
            "https://example.com/index.html?view=panel",
            "file:///index.html?view=panel",
            "http://127.0.0.1:9999/index.html?view=panel",
            "tauri://localhost/index.html?view=history",
            "tauri://localhost/index.html?view=panel&extra=1",
            "tauri://localhost/index.html",
        ] {
            assert!(
                !navigation_is_allowed("panel", &url.parse().unwrap()),
                "expected deny: {url}"
            );
        }
    }

    #[test]
    fn panel_position_centers_near_the_top_of_the_work_area() {
        let work_area = PhysicalBounds::new(0, 0, 1920, 1040);

        assert_eq!(
            panel_position_for_work_area(work_area, 680, 460),
            (620, 130)
        );
    }

    #[test]
    fn panel_position_stays_inside_small_or_offset_monitors() {
        let tiny = PhysicalBounds::new(100, 50, 800, 500);

        let (x, y) = panel_position_for_work_area(tiny, 680, 460);
        assert!(x >= tiny.x);
        assert!(y >= tiny.y);

        let offset = PhysicalBounds::new(-1920, 0, 1920, 1040);
        let (x, y) = panel_position_for_work_area(offset, 680, 460);
        assert_eq!(x, -1920 + (1920 - 680) / 2);
        assert_eq!(y, 130);
    }

    #[test]
    fn reuse_intents_accept_only_a_known_kind_and_bounded_history_id() {
        assert!(reuse_intent_is_valid("input", "history-42"));
        assert!(reuse_intent_is_valid("result", "record_42"));
        assert!(!reuse_intent_is_valid("script", "history-42"));
        assert!(!reuse_intent_is_valid("input", "../../private"));
        assert!(!reuse_intent_is_valid("input", ""));
    }

    #[test]
    fn history_navigation_allows_only_the_fixed_local_entry() {
        for url in [
            "tauri://localhost/index.html?view=history",
            "http://tauri.localhost/index.html?view=history",
            "http://127.0.0.1:1420/index.html?view=history",
        ] {
            assert!(
                is_local_history_url(&url.parse().unwrap()),
                "expected allow: {url}"
            );
        }
        for url in [
            "https://example.com/index.html?view=history",
            "file:///index.html?view=history",
            "http://127.0.0.1:9999/index.html?view=history",
            "http://localhost:1420/index.html?view=history",
            "tauri://localhost/index.html?view=other",
            "tauri://localhost/index.html?view=history&extra=1",
        ] {
            assert!(
                !is_local_history_url(&url.parse().unwrap()),
                "expected deny: {url}"
            );
        }
    }

    #[test]
    fn main_navigation_allows_only_trusted_local_entries() {
        for url in [
            "tauri://localhost/",
            "tauri://localhost/index.html",
            "http://tauri.localhost/",
            "https://tauri.localhost/index.html",
            "http://127.0.0.1:1420/",
            "http://127.0.0.1:1420/index.html",
        ] {
            assert!(
                navigation_is_allowed("main", &url.parse().unwrap()),
                "expected allow: {url}"
            );
        }
    }

    #[test]
    fn navigation_guard_rejects_external_and_dangerous_urls_for_every_window() {
        for label in ["main", "history"] {
            for url in [
                "https://example.com/",
                "http://example.com/",
                "file:///C:/Windows/System32/drivers/etc/hosts",
                "javascript:alert(1)",
                "data:text/html,<script>alert(1)</script>",
                "http://127.0.0.1:1421/",
                "http://localhost:1420/",
            ] {
                assert!(
                    !navigation_is_allowed(label, &url.parse().unwrap()),
                    "expected deny for {label}: {url}"
                );
            }
        }
    }

    #[test]
    fn navigation_guard_enforces_each_window_fixed_entry() {
        for url in [
            "tauri://localhost/index.html?view=history",
            "http://tauri.localhost/index.html?view=history",
            "http://127.0.0.1:1420/index.html?view=history",
        ] {
            let url = url.parse().unwrap();
            assert!(navigation_is_allowed("history", &url));
            assert!(!navigation_is_allowed("main", &url));
        }

        assert!(!navigation_is_allowed(
            "history",
            &"tauri://localhost/index.html".parse().unwrap()
        ));
        assert!(!navigation_is_allowed(
            "settings",
            &"tauri://localhost/index.html".parse().unwrap()
        ));
    }

    #[test]
    fn release_navigation_rejects_the_development_server() {
        let url = "http://127.0.0.1:1420/index.html".parse().unwrap();

        assert!(navigation_is_allowed_for_environment("main", &url, true));
        assert!(!navigation_is_allowed_for_environment("main", &url, false));
    }

    #[test]
    fn navigation_guard_rejects_credentials_on_a_trusted_host() {
        for url in [
            "http://user@tauri.localhost/",
            "https://user:password@tauri.localhost/index.html",
        ] {
            assert!(!navigation_is_allowed("main", &url.parse().unwrap()));
        }
    }
}
