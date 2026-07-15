use std::env;
use std::io::Cursor;
use std::time::Duration;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use image::codecs::png::PngEncoder;
use image::{ExtendedColorType, ImageEncoder};
use reqwest::{Client, Method, StatusCode, Url};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use tauri::{Emitter, State, WebviewWindow};

use crate::cloud_token_store::CloudTokenStore;

const FEEDBACK_UNAVAILABLE: &str = "反馈服务暂不可用，请稍后重试。";
const FEEDBACK_CAPTURE_FAILED: &str = "当前窗口截图失败，可以移除截图后继续反馈。";
const FEEDBACK_SUBMIT_FAILED: &str = "反馈发送失败，请稍后重试。";
const FEEDBACK_CONSENT_REQUIRED: &str = "请先在设置中开启对应的隐私授权。";
const FEEDBACK_CONSENT_OUTDATED: &str = "隐私授权已更新，请刷新设置后重新提交。";
const FEEDBACK_RATE_LIMITED: &str = "反馈提交过于频繁，请稍后再试。";
const FEEDBACK_REQUEST_INVALID: &str = "反馈内容不完整，请检查后重试。";
const CLOUD_UNAVAILABLE: &str = "云端服务暂不可用，请稍后重试。";
const CLOUD_RATE_LIMITED: &str = "云端免费额度已用完或请求过于频繁。";
const CLOUD_PROTOCOL_INVALID: &str = "云端服务返回了无效数据。";
const CLOUD_REQUEST_INVALID: &str = "请求内容无效，请检查后重试。";
const CLOUD_INSTALLATION_UNAUTHORIZED: &str = "安装身份已失效，请重新打开应用。";
const CLOUD_QUOTA_EXHAUSTED: &str = "今日免费额度已用完，可明天再试或使用自备 Provider。";
const CLOUD_INPUT_TOO_LARGE: &str = "输入内容过长，请缩短后重试。";
const CLOUD_QUOTA_UNAVAILABLE: &str = "免费额度服务暂时不可用，请稍后再试。";
const CLOUD_IP_RATE_LIMITED: &str = "当前网络请求过于频繁，请稍后再试。";
const CLOUD_IP_QUOTA_UNAVAILABLE: &str = "网络限流服务暂时不可用，请稍后再试。";
const CLOUD_GLOBAL_REQUEST_BUDGET_EXHAUSTED: &str =
    "今日云端请求额度已用完，请明天再试或切换到自备 Provider。";
const CLOUD_GLOBAL_COST_BUDGET_EXHAUSTED: &str =
    "今日云端服务预算已用完，请稍后再试或切换到自备 Provider。";
const CLOUD_BUDGET_PRICING_UNCONFIGURED: &str = "云端计费配置暂不可用，请稍后再试。";
const CLOUD_BUDGET_UNAVAILABLE: &str = "云端预算服务暂时不可用，请稍后再试。";
const CLOUD_PROVIDER_UNCONFIGURED: &str =
    "云端 Provider 尚未配置，请改用自备 Provider 或联系管理员。";
const CLOUD_CAPACITY_REACHED: &str = "云端当前繁忙，请稍后重试。";
const CLOUD_INSTALLATION_CONCURRENCY_REACHED: &str = "当前安装已有请求处理中，请等待完成。";
const CLOUD_REQUEST_CONFLICT: &str = "该请求正在处理中，请勿重复提交。";
const CLOUD_CONSENT_REQUIRED: &str = "请先在隐私设置中开启对应的数据改进授权。";
const CLOUD_CONSENT_OUTDATED: &str = "隐私授权版本已更新，请刷新授权设置后再提交。";
const MAX_CLOUD_ERROR_BODY: usize = 16 * 1024;
const MAX_CLOUD_STREAM_BUFFER: usize = 512 * 1024;
const MAX_CLOUD_STREAM_EVENTS: usize = 50_000;

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

#[derive(Debug, Deserialize, Serialize)]
pub struct CloudOptimizePayload {
    request_id: String,
    text: String,
    mode: String,
    style: String,
    scene: Option<String>,
    scene_policy: String,
    language: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CloudRequestId {
    request_id: String,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CloudConsent {
    usage_metrics: bool,
    improvement_data: bool,
    feedback_attachments: bool,
    policy_version: String,
    updated_at: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct CloudQuota {
    usage_date: String,
    requests_used: u64,
    requests_limit: u64,
    input_chars_used: u64,
    input_chars_limit: u64,
    output_chars_used: u64,
    output_chars_limit: u64,
}

#[derive(Debug, Deserialize)]
struct CloudCancelResult {
    cancelled: bool,
}

#[derive(Debug, Deserialize)]
struct CloudErrorEnvelope {
    error: CloudErrorBody,
}

#[derive(Debug, Deserialize)]
struct CloudErrorBody {
    code: String,
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
            .timeout(Duration::from_secs(130))
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
            return Err(feedback_error_from_response(response).await);
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

    async fn send_authenticated(
        &self,
        method: Method,
        path: &str,
        body: Option<Value>,
    ) -> Result<reqwest::Response, &'static str> {
        for attempt in 0..2 {
            let token = self.installation_token().await?;
            let mut request = self
                .client
                .request(method.clone(), self.endpoint(path)?)
                .header("X-Reflex-Installation-Token", token);
            if let Some(value) = body.as_ref() {
                request = request.json(value);
            }
            let response = request.send().await.map_err(|_| CLOUD_UNAVAILABLE)?;
            if response.status() != StatusCode::UNAUTHORIZED || attempt == 1 {
                return Ok(response);
            }
            self.token_store.delete().map_err(|_| CLOUD_UNAVAILABLE)?;
        }
        Err(CLOUD_UNAVAILABLE)
    }

    async fn cloud_optimize(
        &self,
        window: &WebviewWindow,
        payload: &CloudOptimizePayload,
    ) -> Result<(), &'static str> {
        validate_cloud_optimize_payload(payload)?;
        let body = serde_json::to_value(payload).map_err(|_| CLOUD_PROTOCOL_INVALID)?;
        let response = self
            .send_authenticated(Method::POST, "v1/optimize", Some(body))
            .await?;
        let mut response = require_cloud_success(response).await?;
        let mut buffer = Vec::new();
        let mut event_count = 0_usize;
        while let Some(chunk) = response.chunk().await.map_err(|_| CLOUD_UNAVAILABLE)? {
            buffer.extend_from_slice(&chunk);
            for envelope in drain_sse_envelopes(&mut buffer, &payload.request_id)? {
                event_count += 1;
                if event_count > MAX_CLOUD_STREAM_EVENTS {
                    return Err(CLOUD_PROTOCOL_INVALID);
                }
                window
                    .emit("reflex://cloud-event", envelope)
                    .map_err(|_| CLOUD_UNAVAILABLE)?;
            }
            if buffer.len() > MAX_CLOUD_STREAM_BUFFER {
                return Err(CLOUD_PROTOCOL_INVALID);
            }
        }
        if !buffer.iter().all(u8::is_ascii_whitespace) || event_count == 0 {
            return Err(CLOUD_PROTOCOL_INVALID);
        }
        Ok(())
    }

    async fn cloud_cancel(&self, request_id: &str) -> Result<bool, &'static str> {
        validate_request_id(request_id)?;
        let body = serde_json::json!({ "request_id": request_id });
        let response = self
            .send_authenticated(Method::POST, "v1/optimize/cancel", Some(body))
            .await?;
        let response = require_cloud_success(response).await?;
        response
            .json::<CloudCancelResult>()
            .await
            .map(|result| result.cancelled)
            .map_err(|_| CLOUD_PROTOCOL_INVALID)
    }

    async fn cloud_consent(&self) -> Result<CloudConsent, &'static str> {
        let response = self
            .send_authenticated(Method::GET, "v1/privacy/consent", None)
            .await?;
        let response = require_cloud_success(response).await?;
        response.json().await.map_err(|_| CLOUD_PROTOCOL_INVALID)
    }

    async fn update_cloud_consent(
        &self,
        consent: &CloudConsent,
    ) -> Result<CloudConsent, &'static str> {
        let body = serde_json::json!({
            "usage_metrics": consent.usage_metrics,
            "improvement_data": consent.improvement_data,
            "feedback_attachments": consent.feedback_attachments,
            "policy_version": consent.policy_version,
        });
        let response = self
            .send_authenticated(Method::PUT, "v1/privacy/consent", Some(body))
            .await?;
        let response = require_cloud_success(response).await?;
        response.json().await.map_err(|_| CLOUD_PROTOCOL_INVALID)
    }

    async fn cloud_quota(&self) -> Result<CloudQuota, &'static str> {
        let response = self
            .send_authenticated(Method::GET, "v1/quota", None)
            .await?;
        let response = require_cloud_success(response).await?;
        response.json().await.map_err(|_| CLOUD_PROTOCOL_INVALID)
    }

    async fn delete_cloud_data(&self) -> Result<bool, &'static str> {
        let response = self
            .send_authenticated(Method::DELETE, "v1/privacy/data", None)
            .await?;
        let _response = require_cloud_success(response).await?;
        self.token_store.delete().map_err(|_| CLOUD_UNAVAILABLE)?;
        Ok(true)
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

#[tauri::command]
pub async fn cloud_optimize(
    window: WebviewWindow,
    state: State<'_, FeedbackCloudState>,
    payload: CloudOptimizePayload,
) -> Result<(), String> {
    require_main_window(window.label())?;
    state
        .cloud_optimize(&window, &payload)
        .await
        .map_err(str::to_string)
}

#[tauri::command]
pub async fn cloud_cancel(
    window: WebviewWindow,
    state: State<'_, FeedbackCloudState>,
    payload: CloudRequestId,
) -> Result<bool, String> {
    require_main_window(window.label())?;
    state
        .cloud_cancel(&payload.request_id)
        .await
        .map_err(str::to_string)
}

#[tauri::command]
pub async fn cloud_get_consent(
    window: WebviewWindow,
    state: State<'_, FeedbackCloudState>,
) -> Result<CloudConsent, String> {
    require_main_window(window.label())?;
    state.cloud_consent().await.map_err(str::to_string)
}

#[tauri::command]
pub async fn cloud_update_consent(
    window: WebviewWindow,
    state: State<'_, FeedbackCloudState>,
    consent: CloudConsent,
) -> Result<CloudConsent, String> {
    require_main_window(window.label())?;
    state
        .update_cloud_consent(&consent)
        .await
        .map_err(str::to_string)
}

#[tauri::command]
pub async fn cloud_get_quota(
    window: WebviewWindow,
    state: State<'_, FeedbackCloudState>,
) -> Result<CloudQuota, String> {
    require_main_window(window.label())?;
    state.cloud_quota().await.map_err(str::to_string)
}

#[tauri::command]
pub async fn cloud_delete_data(
    window: WebviewWindow,
    state: State<'_, FeedbackCloudState>,
) -> Result<bool, String> {
    require_main_window(window.label())?;
    state.delete_cloud_data().await.map_err(str::to_string)
}

async fn require_cloud_success(
    response: reqwest::Response,
) -> Result<reqwest::Response, &'static str> {
    if response.status().is_success() {
        Ok(response)
    } else {
        Err(cloud_error_from_response(response).await)
    }
}

async fn cloud_error_from_response(response: reqwest::Response) -> &'static str {
    let status = response.status();
    let code = error_code_from_response(response).await;
    cloud_error_for_status(status, code.as_deref())
}

fn cloud_error_for_status(status: StatusCode, code: Option<&str>) -> &'static str {
    match code {
        Some("request_invalid" | "budget_input_invalid") => CLOUD_REQUEST_INVALID,
        Some("installation_unauthorized") => CLOUD_INSTALLATION_UNAUTHORIZED,
        Some("quota_exhausted") => CLOUD_QUOTA_EXHAUSTED,
        Some("quota_input_too_large") => CLOUD_INPUT_TOO_LARGE,
        Some("quota_unavailable") => CLOUD_QUOTA_UNAVAILABLE,
        Some("ip_rate_limited") => CLOUD_IP_RATE_LIMITED,
        Some("ip_quota_unavailable") => CLOUD_IP_QUOTA_UNAVAILABLE,
        Some("global_request_budget_exhausted") => CLOUD_GLOBAL_REQUEST_BUDGET_EXHAUSTED,
        Some("global_cost_budget_exhausted") => CLOUD_GLOBAL_COST_BUDGET_EXHAUSTED,
        Some("budget_pricing_unconfigured") => CLOUD_BUDGET_PRICING_UNCONFIGURED,
        Some("budget_unavailable") => CLOUD_BUDGET_UNAVAILABLE,
        Some("cloud_provider_unconfigured") => CLOUD_PROVIDER_UNCONFIGURED,
        Some("cloud_capacity_reached") => CLOUD_CAPACITY_REACHED,
        Some("installation_concurrency_reached") => CLOUD_INSTALLATION_CONCURRENCY_REACHED,
        Some("optimize_request_conflict") => CLOUD_REQUEST_CONFLICT,
        Some("consent_required") => CLOUD_CONSENT_REQUIRED,
        Some("consent_outdated") => CLOUD_CONSENT_OUTDATED,
        _ if status == StatusCode::TOO_MANY_REQUESTS => CLOUD_RATE_LIMITED,
        _ if status == StatusCode::PAYLOAD_TOO_LARGE => CLOUD_INPUT_TOO_LARGE,
        _ if matches!(
            status,
            StatusCode::BAD_REQUEST | StatusCode::UNPROCESSABLE_ENTITY
        ) =>
        {
            CLOUD_REQUEST_INVALID
        }
        _ if status == StatusCode::UNAUTHORIZED => CLOUD_INSTALLATION_UNAUTHORIZED,
        _ => CLOUD_UNAVAILABLE,
    }
}

async fn error_code_from_response(mut response: reqwest::Response) -> Option<String> {
    if response
        .content_length()
        .is_some_and(|length| length > MAX_CLOUD_ERROR_BODY as u64)
    {
        return None;
    }
    let mut body = Vec::new();
    loop {
        match response.chunk().await {
            Ok(Some(chunk)) => {
                if chunk.len() > MAX_CLOUD_ERROR_BODY.saturating_sub(body.len()) {
                    return None;
                }
                body.extend_from_slice(&chunk);
            }
            Ok(None) => break,
            Err(_) => return None,
        }
    }
    error_code_from_body(&body)
}

fn error_code_from_body(body: &[u8]) -> Option<String> {
    serde_json::from_slice::<CloudErrorEnvelope>(body)
        .ok()
        .map(|payload| payload.error.code)
}

async fn feedback_error_from_response(response: reqwest::Response) -> &'static str {
    let status = response.status();
    let code = error_code_from_response(response).await;
    feedback_error_for_status(status, code.as_deref())
}

fn feedback_error_for_status(status: StatusCode, code: Option<&str>) -> &'static str {
    match code {
        Some("consent_required") => FEEDBACK_CONSENT_REQUIRED,
        Some("consent_outdated") => FEEDBACK_CONSENT_OUTDATED,
        Some("feedback_rate_limited") => FEEDBACK_RATE_LIMITED,
        Some("request_invalid") => FEEDBACK_REQUEST_INVALID,
        _ if status == StatusCode::TOO_MANY_REQUESTS => FEEDBACK_RATE_LIMITED,
        _ => FEEDBACK_SUBMIT_FAILED,
    }
}

fn validate_request_id(request_id: &str) -> Result<(), &'static str> {
    if (8..=128).contains(&request_id.len())
        && request_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
    {
        Ok(())
    } else {
        Err(CLOUD_PROTOCOL_INVALID)
    }
}

fn validate_cloud_optimize_payload(payload: &CloudOptimizePayload) -> Result<(), &'static str> {
    validate_request_id(&payload.request_id)?;
    if payload.text.trim().is_empty()
        || payload.text.len() > 100_000
        || !matches!(payload.mode.as_str(), "content" | "prompt")
        || !matches!(
            payload.style.as_str(),
            "concise" | "balanced" | "detailed" | "creative" | "precise"
        )
        || !matches!(payload.scene_policy.as_str(), "auto" | "manual" | "ask")
        || !matches!(payload.language.as_str(), "zh-CN" | "en-US")
        || payload.scene.as_ref().is_some_and(|value| value.len() > 64)
        || (payload.scene_policy == "manual" && payload.scene.is_none())
    {
        Err(CLOUD_PROTOCOL_INVALID)
    } else {
        Ok(())
    }
}

fn drain_sse_envelopes(
    buffer: &mut Vec<u8>,
    expected_request_id: &str,
) -> Result<Vec<Value>, &'static str> {
    let mut envelopes = Vec::new();
    while let Some(end) = buffer.windows(2).position(|window| window == b"\n\n") {
        let frame = buffer.drain(..end + 2).collect::<Vec<_>>();
        let text = std::str::from_utf8(&frame[..end]).map_err(|_| CLOUD_PROTOCOL_INVALID)?;
        let data = text
            .lines()
            .filter_map(|line| line.trim_end_matches('\r').strip_prefix("data: "))
            .collect::<Vec<_>>()
            .join("\n");
        if data.is_empty() {
            continue;
        }
        let value: Value = serde_json::from_str(&data).map_err(|_| CLOUD_PROTOCOL_INVALID)?;
        validate_cloud_envelope(&value, expected_request_id)?;
        envelopes.push(value);
    }
    Ok(envelopes)
}

fn validate_cloud_envelope(value: &Value, expected_request_id: &str) -> Result<(), &'static str> {
    let event_type = value
        .get("event")
        .and_then(|event| event.get("type"))
        .and_then(Value::as_str);
    if value.get("version").and_then(Value::as_u64) != Some(1)
        || value.get("request_id").and_then(Value::as_str) != Some(expected_request_id)
        || !matches!(
            event_type,
            Some("status" | "scene" | "request" | "chunk" | "done" | "error" | "metric")
        )
        || !value
            .get("event")
            .and_then(|event| event.get("data"))
            .is_some_and(Value::is_object)
    {
        Err(CLOUD_PROTOCOL_INVALID)
    } else {
        Ok(())
    }
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
    use reqwest::StatusCode;

    use super::{
        cloud_error_for_status, drain_sse_envelopes, error_code_from_body, feedback_base_url,
        feedback_error_for_status, validate_cloud_optimize_payload, validate_feedback_payload,
        CloudOptimizePayload, FeedbackContext, FeedbackPayload, CLOUD_RATE_LIMITED,
        CLOUD_UNAVAILABLE, FEEDBACK_CONSENT_OUTDATED, FEEDBACK_CONSENT_REQUIRED,
        FEEDBACK_RATE_LIMITED, FEEDBACK_REQUEST_INVALID, FEEDBACK_SUBMIT_FAILED,
    };

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
    fn feedback_errors_use_only_actionable_whitelisted_messages() {
        assert_eq!(
            feedback_error_for_status(StatusCode::FORBIDDEN, Some("consent_required")),
            FEEDBACK_CONSENT_REQUIRED
        );
        assert_eq!(
            feedback_error_for_status(StatusCode::CONFLICT, Some("consent_outdated")),
            FEEDBACK_CONSENT_OUTDATED
        );
        assert_eq!(
            feedback_error_for_status(StatusCode::TOO_MANY_REQUESTS, Some("feedback_rate_limited")),
            FEEDBACK_RATE_LIMITED
        );
        assert_eq!(
            feedback_error_for_status(StatusCode::UNPROCESSABLE_ENTITY, Some("request_invalid")),
            FEEDBACK_REQUEST_INVALID
        );
        assert_eq!(
            feedback_error_for_status(StatusCode::BAD_GATEWAY, Some("provider-internal-detail")),
            FEEDBACK_SUBMIT_FAILED
        );
    }

    #[test]
    fn cloud_errors_map_only_whitelisted_codes_to_actionable_messages() {
        let cases = [
            ("request_invalid", "请求内容无效，请检查后重试。"),
            (
                "installation_unauthorized",
                "安装身份已失效，请重新打开应用。",
            ),
            (
                "quota_exhausted",
                "今日免费额度已用完，可明天再试或使用自备 Provider。",
            ),
            ("quota_input_too_large", "输入内容过长，请缩短后重试。"),
            ("quota_unavailable", "免费额度服务暂时不可用，请稍后再试。"),
            ("ip_rate_limited", "当前网络请求过于频繁，请稍后再试。"),
            (
                "ip_quota_unavailable",
                "网络限流服务暂时不可用，请稍后再试。",
            ),
            (
                "global_request_budget_exhausted",
                "今日云端请求额度已用完，请明天再试或切换到自备 Provider。",
            ),
            (
                "global_cost_budget_exhausted",
                "今日云端服务预算已用完，请稍后再试或切换到自备 Provider。",
            ),
            (
                "budget_pricing_unconfigured",
                "云端计费配置暂不可用，请稍后再试。",
            ),
            ("budget_unavailable", "云端预算服务暂时不可用，请稍后再试。"),
            (
                "cloud_provider_unconfigured",
                "云端 Provider 尚未配置，请改用自备 Provider 或联系管理员。",
            ),
            ("cloud_capacity_reached", "云端当前繁忙，请稍后重试。"),
            (
                "installation_concurrency_reached",
                "当前安装已有请求处理中，请等待完成。",
            ),
            (
                "optimize_request_conflict",
                "该请求正在处理中，请勿重复提交。",
            ),
            (
                "consent_required",
                "请先在隐私设置中开启对应的数据改进授权。",
            ),
            (
                "consent_outdated",
                "隐私授权版本已更新，请刷新授权设置后再提交。",
            ),
        ];

        for (code, expected) in cases {
            assert_eq!(
                cloud_error_for_status(StatusCode::SERVICE_UNAVAILABLE, Some(code)),
                expected
            );
        }
    }

    #[test]
    fn cloud_errors_never_echo_untrusted_server_messages() {
        let body =
            br#"{"error":{"code":"provider-internal-detail","message":"api_key=private-value"}}"#;
        let code = error_code_from_body(body);
        let message = cloud_error_for_status(StatusCode::BAD_GATEWAY, code.as_deref());

        assert_eq!(message, CLOUD_UNAVAILABLE);
        assert!(!message.contains("private-value"));
        assert_eq!(
            cloud_error_for_status(StatusCode::TOO_MANY_REQUESTS, None),
            CLOUD_RATE_LIMITED
        );
    }

    #[test]
    fn development_default_feedback_endpoint_is_loopback_only() {
        let endpoint = feedback_base_url().unwrap();
        assert_eq!(endpoint.as_str(), "http://127.0.0.1:8787/");
    }

    #[test]
    fn cloud_payload_and_sse_envelopes_are_strictly_bounded_to_the_request() {
        let payload = CloudOptimizePayload {
            request_id: "request-cloud-1".into(),
            text: "fixture".into(),
            mode: "content".into(),
            style: "balanced".into(),
            scene: None,
            scene_policy: "auto".into(),
            language: "zh-CN".into(),
        };
        assert!(validate_cloud_optimize_payload(&payload).is_ok());
        let mut bytes = b"data: {\"version\":1,\"request_id\":\"request-cloud-1\",\"event\":{\"type\":\"chunk\",\"data\":{\"text\":\"ok\"}}}\n\n".to_vec();

        let events = drain_sse_envelopes(&mut bytes, "request-cloud-1").unwrap();

        assert_eq!(events.len(), 1);
        assert!(bytes.is_empty());
        let mut forged = b"data: {\"version\":1,\"request_id\":\"other\",\"event\":{\"type\":\"chunk\",\"data\":{}}}\n\n".to_vec();
        assert!(drain_sse_envelopes(&mut forged, "request-cloud-1").is_err());
    }
}
