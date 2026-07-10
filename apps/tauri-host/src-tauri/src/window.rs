use tauri::{AppHandle, Manager, PhysicalPosition, Runtime};

const MIN_VISIBLE_EDGE: i64 = 64;
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
    if window.is_minimized().unwrap_or(false) {
        let _ = window.unminimize();
    }
    window.show().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)?;
    window.set_focus().map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

pub fn hide_main_window<R: Runtime>(app: &AppHandle<R>) -> Result<(), &'static str> {
    app.get_webview_window("main")
        .ok_or(WINDOW_UNAVAILABLE_MESSAGE)?
        .hide()
        .map_err(|_| WINDOW_UNAVAILABLE_MESSAGE)
}

fn recover_main_window_position<R: Runtime>(window: &tauri::WebviewWindow<R>) {
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
    use super::{recover_window_position, PhysicalBounds};

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
}
