use std::env;
use std::io::Cursor;
use std::time::Duration;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use image::codecs::png::PngEncoder;
use image::{ExtendedColorType, ImageEncoder};
use reqwest::{Client, StatusCode, Url};
use serde::{Deserialize, Serialize};
use tauri::{State, WebviewWindow};

use crate::cloud_token_store::CloudTokenStore;

const FEEDBACK_UNAVAILABLE: &str = "反馈服务暂不可用，请稍后重试。";
const FEEDBACK_CAPTURE_FAILED: &str = "当前窗口截图失败，可以移除截图后继续反馈。";
const FEEDBACK_SUBMIT_FAILED: &str = "反馈发送失败，请稍后重试。";

#[derive(Debug, Clone, Serialize)]
pub struct FeedbackScreenshot {
    media_type: &'static str,
    data_base64: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct FeedbackPayload {
    sentiment: String,
    category: String,
    message: String,
    expected_output: String,
    contact: String,
    context: FeedbackContext,
    include_prompt: bool,
    include_result: bool,
    include_screenshot: bool,
    prompt_text: Option<String>,
    result_text: Option<String>,
    screenshot: Option<FeedbackScreenshotInput>,
    consent_version: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct FeedbackContext {
    app_version: String,
    os_version: String,
    provider: String,
    model: String,
    mode: String,
    style: String,
    scene: String,
    request_id: String,
    diagnostic_id: String,
    error_code: String,
    elapsed_ms: Option<u64>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct FeedbackScreenshotInput {
    media_type: String,
    data_base64: String,
}

#[derive(Debug, Deserialize)]
struct InstallationCreated {
    token: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct FeedbackSubmitted {
    id: String,
    status: String,
}

pub struct FeedbackCloudState {
    client: Client,
    token_store: CloudTokenStore,
    base_url: Option<Url>,
}

impl FeedbackCloudState {
    pub fn new() -> Self {
        let client = Client::builder()
            .connect_timeout(Duration::from_secs(5))
            .timeout(Duration::from_secs(25))
            .user_agent("Reflex-Desktop/0.7")
            .build()
            .expect("feedback HTTP client configuration is valid");
        Self {
            client,
            token_store: CloudTokenStore::windows(),
            base_url: feedback_base_url(),
        }
    }

    async fn submit(&self, payload: &FeedbackPayload) -> Result<FeedbackSubmitted, &'static str> {
        validate_feedback_payload(payload)?;
        let mut token = self.installation_token().await?;
        let mut response = self.send_feedback(&token, payload).await?;
        if response.status() == StatusCode::UNAUTHORIZED {
            self.token_store
                .delete()
                .map_err(|_| FEEDBACK_UNAVAILABLE)?;
            token = self.installation_token().await?;
            response = self.send_feedback(&token, payload).await?;
        }
        if !response.status().is_success() {
            return Err(FEEDBACK_SUBMIT_FAILED);
        }
        response
            .json::<FeedbackSubmitted>()
            .await
            .map_err(|_| FEEDBACK_SUBMIT_FAILED)
    }

    async fn installation_token(&self) -> Result<String, &'static str> {
        if let Some(token) = self.token_store.read().map_err(|_| FEEDBACK_UNAVAILABLE)? {
            return Ok(token);
        }
        let endpoint = self.endpoint("v1/installations")?;
        let response = self
            .client
            .post(endpoint)
            .send()
            .await
            .map_err(|_| FEEDBACK_UNAVAILABLE)?;
        if response.status() != StatusCode::CREATED {
            return Err(FEEDBACK_UNAVAILABLE);
        }
        let created = response
            .json::<InstallationCreated>()
            .await
            .map_err(|_| FEEDBACK_UNAVAILABLE)?;
        self.token_store
            .save(&created.token)
            .map_err(|_| FEEDBACK_UNAVAILABLE)?;
        Ok(created.token)
    }

    async fn send_feedback(
        &self,
        token: &str,
        payload: &FeedbackPayload,
    ) -> Result<reqwest::Response, &'static str> {
        self.client
            .post(self.endpoint("v1/feedback")?)
            .header("X-Reflex-Installation-Token", token)
            .json(payload)
            .send()
            .await
            .map_err(|_| FEEDBACK_SUBMIT_FAILED)
    }

    fn endpoint(&self, path: &str) -> Result<Url, &'static str> {
        self.base_url
            .as_ref()
            .ok_or(FEEDBACK_UNAVAILABLE)?
            .join(path)
            .map_err(|_| FEEDBACK_UNAVAILABLE)
    }
}

#[tauri::command]
pub async fn capture_feedback_screenshot(
    window: WebviewWindow,
) -> Result<FeedbackScreenshot, String> {
    require_main_window(window.label())?;
    let png = capture_window_png(&window).map_err(str::to_string)?;
    Ok(FeedbackScreenshot {
        media_type: "image/png",
        data_base64: STANDARD.encode(png),
    })
}

#[tauri::command]
pub async fn submit_feedback(
    state: State<'_, FeedbackCloudState>,
    payload: FeedbackPayload,
) -> Result<FeedbackSubmitted, String> {
    state.submit(&payload).await.map_err(str::to_string)
}

fn feedback_base_url() -> Option<Url> {
    let configured = env::var("REFLEX_CLOUD_BASE_URL").ok();
    let raw = configured.as_deref().unwrap_or(if cfg!(debug_assertions) {
        "http://127.0.0.1:8787/"
    } else {
        ""
    });
    let url = Url::parse(raw).ok()?;
    if url.username() != ""
        || url.password().is_some()
        || url.query().is_some()
        || url.fragment().is_some()
    {
        return None;
    }
    if url.scheme() == "https" {
        return Some(url);
    }
    if cfg!(debug_assertions)
        && url.scheme() == "http"
        && url.host_str().is_some_and(is_loopback_host)
    {
        return Some(url);
    }
    None
}

fn is_loopback_host(host: &str) -> bool {
    matches!(host, "127.0.0.1" | "localhost" | "[::1]")
}

fn validate_feedback_payload(payload: &FeedbackPayload) -> Result<(), &'static str> {
    if !matches!(payload.sentiment.as_str(), "positive" | "negative")
        || !matches!(
            payload.category.as_str(),
            "quality" | "bug" | "performance" | "feature" | "other"
        )
        || payload.message.len() > 4_000
        || payload.expected_output.len() > 10_000
        || payload.contact.len() > 320
        || payload.consent_version.len() > 32
        || payload.context.app_version.len() > 64
        || payload.context.os_version.len() > 128
        || payload
            .prompt_text
            .as_ref()
            .is_some_and(|value| value.len() > 100_000)
        || payload
            .result_text
            .as_ref()
            .is_some_and(|value| value.len() > 100_000)
        || payload.include_prompt != payload.prompt_text.is_some()
        || payload.include_result != payload.result_text.is_some()
        || payload.include_screenshot != payload.screenshot.is_some()
    {
        return Err(FEEDBACK_SUBMIT_FAILED);
    }
    if let Some(screenshot) = &payload.screenshot {
        if screenshot.media_type != "image/png" || screenshot.data_base64.len() > 5_000_000 {
            return Err(FEEDBACK_SUBMIT_FAILED);
        }
    }
    Ok(())
}

fn require_main_window(label: &str) -> Result<(), String> {
    if label == "main" {
        Ok(())
    } else {
        Err(FEEDBACK_CAPTURE_FAILED.to_string())
    }
}

#[cfg(windows)]
fn capture_window_png(window: &WebviewWindow) -> Result<Vec<u8>, &'static str> {
    use std::mem::{size_of, zeroed};

    use windows_sys::Win32::Graphics::Gdi::{
        BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC,
        GetDIBits, ReleaseDC, SelectObject, BITMAPINFO, BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS,
        HGDIOBJ, SRCCOPY,
    };
    use windows_sys::Win32::UI::WindowsAndMessaging::GetClientRect;

    let hwnd = window.hwnd().map_err(|_| FEEDBACK_CAPTURE_FAILED)?.0 as _;
    let mut rect = unsafe { zeroed() };
    if unsafe { GetClientRect(hwnd, &mut rect) } == 0 {
        return Err(FEEDBACK_CAPTURE_FAILED);
    }
    let width = rect.right - rect.left;
    let height = rect.bottom - rect.top;
    if width <= 0 || height <= 0 || width > 4096 || height > 4096 {
        return Err(FEEDBACK_CAPTURE_FAILED);
    }

    let window_dc = unsafe { GetDC(hwnd) };
    if window_dc.is_null() {
        return Err(FEEDBACK_CAPTURE_FAILED);
    }
    let memory_dc = unsafe { CreateCompatibleDC(window_dc) };
    let bitmap = unsafe { CreateCompatibleBitmap(window_dc, width, height) };
    if memory_dc.is_null() || bitmap.is_null() {
        unsafe {
            if !memory_dc.is_null() {
                DeleteDC(memory_dc);
            }
            ReleaseDC(hwnd, window_dc);
        }
        return Err(FEEDBACK_CAPTURE_FAILED);
    }
    let previous = unsafe { SelectObject(memory_dc, bitmap as HGDIOBJ) };
    let copied = unsafe { BitBlt(memory_dc, 0, 0, width, height, window_dc, 0, 0, SRCCOPY) };
    let mut pixels = vec![0_u8; width as usize * height as usize * 4];
    let mut info: BITMAPINFO = unsafe { zeroed() };
    info.bmiHeader = BITMAPINFOHEADER {
        biSize: size_of::<BITMAPINFOHEADER>() as u32,
        biWidth: width,
        biHeight: -height,
        biPlanes: 1,
        biBitCount: 32,
        biCompression: BI_RGB,
        ..unsafe { zeroed() }
    };
    let lines = if copied != 0 {
        unsafe {
            GetDIBits(
                memory_dc,
                bitmap,
                0,
                height as u32,
                pixels.as_mut_ptr().cast(),
                &mut info,
                DIB_RGB_COLORS,
            )
        }
    } else {
        0
    };
    unsafe {
        SelectObject(memory_dc, previous);
        DeleteObject(bitmap as HGDIOBJ);
        DeleteDC(memory_dc);
        ReleaseDC(hwnd, window_dc);
    }
    if lines != height {
        return Err(FEEDBACK_CAPTURE_FAILED);
    }
    for pixel in pixels.chunks_exact_mut(4) {
        pixel.swap(0, 2);
        pixel[3] = 255;
    }
    let mut png = Cursor::new(Vec::new());
    PngEncoder::new(&mut png)
        .write_image(
            &pixels,
            width as u32,
            height as u32,
            ExtendedColorType::Rgba8,
        )
        .map_err(|_| FEEDBACK_CAPTURE_FAILED)?;
    Ok(png.into_inner())
}

#[cfg(not(windows))]
fn capture_window_png(_: &WebviewWindow) -> Result<Vec<u8>, &'static str> {
    Err(FEEDBACK_CAPTURE_FAILED)
}

#[cfg(test)]
mod tests {
    use super::{feedback_base_url, validate_feedback_payload, FeedbackContext, FeedbackPayload};

    fn payload() -> FeedbackPayload {
        FeedbackPayload {
            sentiment: "negative".into(),
            category: "quality".into(),
            message: "not good".into(),
            expected_output: "better".into(),
            contact: String::new(),
            context: FeedbackContext {
                app_version: "0.7.0".into(),
                os_version: "Windows".into(),
                provider: "minimax".into(),
                model: "model".into(),
                mode: "content".into(),
                style: "balanced".into(),
                scene: "general".into(),
                request_id: "request".into(),
                diagnostic_id: String::new(),
                error_code: String::new(),
                elapsed_ms: Some(100),
            },
            include_prompt: false,
            include_result: false,
            include_screenshot: false,
            prompt_text: None,
            result_text: None,
            screenshot: None,
            consent_version: "2026-07-14".into(),
        }
    }

    #[test]
    fn payload_requires_explicit_attachment_flags() {
        let mut invalid = payload();
        invalid.prompt_text = Some("private".into());

        assert!(validate_feedback_payload(&invalid).is_err());
        assert!(validate_feedback_payload(&payload()).is_ok());
    }

    #[test]
    fn development_default_feedback_endpoint_is_loopback_only() {
        let endpoint = feedback_base_url().unwrap();
        assert_eq!(endpoint.as_str(), "http://127.0.0.1:8787/");
    }
}
