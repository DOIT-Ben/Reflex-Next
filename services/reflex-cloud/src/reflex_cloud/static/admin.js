const state = { token: "", selectedId: "", items: [], releases: [] };
const list = document.querySelector("#feedback-list");
const detail = document.querySelector("#detail");
const summary = document.querySelector("#summary");
const tokenInput = document.querySelector("#admin-token");
const statusFilter = document.querySelector("#status");
const categoryFilter = document.querySelector("#category");
const usageRequests = document.querySelector("#usage-requests");
const usageCompletion = document.querySelector("#usage-completion");
const usageCost = document.querySelector("#usage-cost");
const qualityNegative = document.querySelector("#quality-negative");
const qualityVersion = document.querySelector("#quality-version");
const usageBudget = document.querySelector("#usage-budget");
const operationsStatus = document.querySelector("#operations-status");
const currentRelease = document.querySelector("#current-release");
const releaseList = document.querySelector("#release-list");
const releaseStatus = document.querySelector("#release-status");
const releaseForm = document.querySelector("#release-form");
const releaseVersion = document.querySelector("#release-version");
const templatePackVersion = document.querySelector("#template-pack-version");
const releaseTitle = document.querySelector("#release-title");
const releaseSummary = document.querySelector("#release-summary");
const releaseGuidance = document.querySelector("#release-guidance");
const releaseSceneGuidance = document.querySelector("#release-scene-guidance");
const releaseSources = document.querySelector("#release-sources");
const releaseSubmit = releaseForm.querySelector("button[type=submit]");

document.querySelector("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = tokenInput.value;
  tokenInput.value = "";
  await Promise.all([loadFeedback(), loadOperations(), loadReleases()]);
});

document.querySelector("#filters").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadFeedback();
});

document.querySelector("#refresh-releases").addEventListener("click", () => {
  void loadReleases();
});

releaseForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.token) return;
  const sourceIds = releaseSources.value
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  let sceneGuidance = {};
  try {
    const rawSceneGuidance = releaseSceneGuidance.value.trim();
    if (rawSceneGuidance) {
      const parsed = JSON.parse(rawSceneGuidance);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
        throw new Error("场景指导必须是 JSON 对象。");
      }
      for (const [scene, guidance] of Object.entries(parsed)) {
        if (!scene.trim() || typeof guidance !== "string" || !guidance.trim()) {
          throw new Error("场景指导的键和值都必须是非空文本。");
        }
      }
      sceneGuidance = parsed;
    }
    if (!releaseGuidance.value.trim() && !Object.keys(sceneGuidance).length) {
      throw new Error("请至少填写通用质量指导或一条场景指导。");
    }
    releaseSubmit.disabled = true;
    await request("/v1/admin/quality-releases", {
      method: "POST",
      body: JSON.stringify({
        release_version: releaseVersion.value.trim(),
        template_pack_version: templatePackVersion.value.trim(),
        title: releaseTitle.value.trim(),
        summary: releaseSummary.value.trim(),
        global_guidance: releaseGuidance.value.trim(),
        scene_guidance: sceneGuidance,
        source_feedback_ids: sourceIds
      })
    });
    releaseStatus.textContent = "发布草稿已创建，请确认来源反馈均已修复后再发布。";
    await loadReleases();
  } catch (error) {
    releaseStatus.textContent = error.message;
  } finally {
    releaseSubmit.disabled = false;
  }
});

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Authorization: `Bearer ${state.token}`,
      "Content-Type": "application/json",
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    const raw = await response.text();
    let message = "";
    try {
      const payload = JSON.parse(raw);
      message = payload?.error?.message || "";
    } catch {
      // The server may return an HTML or empty error body.
    }
    throw new Error(message || `请求失败 (${response.status})`);
  }
  return response;
}

async function loadFeedback() {
  if (!state.token) return;
  const query = new URLSearchParams();
  if (statusFilter.value) query.set("status", statusFilter.value);
  if (categoryFilter.value) query.set("category", categoryFilter.value);
  try {
    const response = await request(`/v1/admin/feedback?${query}`);
    const payload = await response.json();
    state.items = payload.items;
    summary.textContent = `${payload.total} 条反馈`;
    renderList();
  } catch (error) {
    list.replaceChildren(messageElement(error.message, "error"));
    summary.textContent = "连接失败";
  }
}

async function loadOperations() {
  if (!state.token) return;
  try {
    const [usageResponse, qualityResponse] = await Promise.all([
      request("/v1/admin/analytics/usage?days=7"),
      request("/v1/admin/analytics/feedback")
    ]);
    const usage = await usageResponse.json();
    const quality = await qualityResponse.json();
    usageRequests.textContent = formatNumber(usage.requests);
    usageCompletion.textContent = usage.requests
      ? `${Math.round((usage.completed_requests / usage.requests) * 100)}%`
      : "-";
    usageCost.textContent = usage.pricing_configured
      ? `$${(usage.estimated_cost_microusd / 1_000_000).toFixed(4)}`
      : "未配置单价";
    qualityNegative.textContent = quality.total
      ? `${(quality.negative_rate * 100).toFixed(1)}%`
      : "-";
    qualityVersion.textContent = versionQualityText(quality.by_quality_release, quality.by_version);
    usageBudget.textContent = formatBudget(usage);
    operationsStatus.textContent = `${usage.from_date} 至 ${usage.to_date} · 价格版本 ${usage.pricing_version}`;
  } catch (error) {
    operationsStatus.textContent = error.message;
    usageRequests.textContent = "-";
    usageCompletion.textContent = "-";
    usageCost.textContent = "-";
    qualityNegative.textContent = "-";
    qualityVersion.textContent = "加载失败";
    usageBudget.textContent = "加载失败";
  }
}

async function loadReleases() {
  if (!state.token) return;
  try {
    const response = await request("/v1/admin/quality-releases");
    const payload = await response.json();
    state.releases = payload.items || [];
    const active = state.releases.find((item) => item.status === "published");
    currentRelease.textContent = active
      ? `${active.release_version} · ${active.title}`
      : "未发布";
    releaseStatus.textContent = `${payload.total} 个质量发布`;
    renderReleases();
  } catch (error) {
    currentRelease.textContent = "加载失败";
    releaseStatus.textContent = error.message;
    releaseList.replaceChildren(messageElement(error.message, "error"));
  }
}

function renderReleases() {
  releaseList.replaceChildren();
  if (!state.releases.length) {
    releaseList.append(messageElement("暂无质量发布", "empty"));
    return;
  }
  for (const release of state.releases) {
    const row = document.createElement("div");
    row.className = "release-row";
    const info = document.createElement("div");
    info.append(
      text(`${release.release_version} · ${release.title}`, "strong"),
      text(`${releaseStatusLabel(release.status)} · 来源 ${release.source_feedback_count} 条`, "small"),
      text(release.summary, "p")
    );
    row.append(info);
    if (release.status === "draft") {
      const publish = document.createElement("button");
      publish.type = "button";
      publish.textContent = "发布";
      publish.addEventListener("click", () => void changeReleaseState(release.id, "publish"));
      row.append(publish);
    } else if (release.status === "published") {
      const rollback = document.createElement("button");
      rollback.type = "button";
      rollback.className = "danger";
      rollback.textContent = "回滚";
      rollback.addEventListener("click", () => void changeReleaseState(release.id, "rollback"));
      row.append(rollback);
    }
    releaseList.append(row);
  }
}

async function changeReleaseState(id, action) {
  const question = action === "rollback"
    ? "确定回滚这个质量发布吗？回滚后将恢复上一版（如有）。"
    : "确定发布这个质量改进吗？发布后会影响云端请求。";
  if (!window.confirm(question)) return;
  try {
    await request(`/v1/admin/quality-releases/${encodeURIComponent(id)}/${action}`, { method: "POST" });
    await Promise.all([loadReleases(), loadFeedback()]);
  } catch (error) {
    releaseStatus.textContent = error.message;
  }
}

function renderList() {
  list.replaceChildren();
  if (!state.items.length) {
    list.append(messageElement("暂无反馈", "empty"));
    return;
  }
  for (const item of state.items) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `feedback-row${item.id === state.selectedId ? " active" : ""}`;
    const heading = document.createElement("strong");
    heading.append(text(item.sentiment === "negative" ? "不满意" : "满意"));
    heading.append(text(statusLabel(item.status), "span"));
    button.append(heading);
    button.append(text(`${categoryLabel(item.category)} · ${item.app_version}`, "span"));
    button.append(text(`${item.provider || "未记录"} · ${formatTime(item.created_at)}`, "small"));
    button.addEventListener("click", () => selectFeedback(item.id));
    list.append(button);
  }
}

async function selectFeedback(id) {
  state.selectedId = id;
  renderList();
  try {
    const response = await request(`/v1/admin/feedback/${encodeURIComponent(id)}`);
    renderDetail(await response.json());
  } catch (error) {
    detail.replaceChildren(messageElement(error.message, "error"));
  }
}

function renderDetail(item) {
  detail.replaceChildren();
  const head = document.createElement("div");
  head.className = "detail-head";
  const title = document.createElement("div");
  title.append(text(item.sentiment === "negative" ? "不满意反馈" : "满意反馈", "h1"));
  title.append(text(`${item.category} · ${formatTime(item.created_at)}`, "p"));
  const status = document.createElement("select");
  for (const value of ["new", "triaged", "reproduced", "planned", "fixed", "released", "rejected"]) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = statusLabel(value);
    option.selected = value === item.status;
    status.append(option);
  }
  status.addEventListener("change", () => updateStatus(item.id, status.value));
  const addSource = document.createElement("button");
  addSource.type = "button";
  addSource.className = "outline";
  addSource.textContent = "加入当前发布";
  addSource.addEventListener("click", () => addReleaseSource(item.id));
  head.append(title, addSource, status);
  detail.append(head, metadata(item));
  appendSection("反馈描述", item.message || "未填写");
  appendSection("期望结果", item.expected_output || "未填写");
  if (item.prompt_text) appendSection("授权附加的提示词", item.prompt_text);
  if (item.result_text) appendSection("授权附加的结果", item.result_text);
  if (item.screenshot_url) void appendScreenshot(item.screenshot_url);
}

function addReleaseSource(id) {
  const current = releaseSources.value
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  if (!current.includes(id)) current.push(id);
  releaseSources.value = current.join(", ");
  releaseStatus.textContent = "已加入来源反馈输入框。";
  releaseSources.focus();
}

async function updateStatus(id, status) {
  try {
    const response = await request(`/v1/admin/feedback/${encodeURIComponent(id)}`, {
      method: "PATCH",
      body: JSON.stringify({ status })
    });
    const updated = await response.json();
    await loadFeedback();
    renderDetail(updated);
  } catch (error) {
    detail.prepend(messageElement(error.message, "error"));
  }
}

function metadata(item) {
  const values = {
    版本: item.context.app_version,
    系统: item.context.os_version,
    Provider: item.context.provider,
    模型: item.context.model,
    场景: item.context.scene,
    耗时: item.context.elapsed_ms == null ? "未记录" : `${item.context.elapsed_ms} ms`,
    请求ID: item.context.request_id,
    诊断ID: item.context.diagnostic_id,
    错误代码: item.context.error_code,
    授权版本: item.consent_version
  };
  const dl = document.createElement("dl");
  dl.className = "meta";
  for (const [label, value] of Object.entries(values)) {
    const group = document.createElement("div");
    group.append(text(label, "dt"), text(value || "未记录", "dd"));
    dl.append(group);
  }
  return dl;
}

function appendSection(title, content) {
  const section = document.createElement("section");
  section.className = "content-section";
  section.append(text(title, "h2"), text(content, "pre"));
  detail.append(section);
}

async function appendScreenshot(url) {
  const section = document.createElement("section");
  section.className = "content-section";
  section.append(text("应用截图", "h2"));
  try {
    const response = await request(url, { headers: { Accept: "image/*" } });
    const image = document.createElement("img");
    image.className = "feedback-shot";
    image.alt = "用户授权提交的 Reflex 应用截图";
    image.src = URL.createObjectURL(await response.blob());
    image.addEventListener("load", () => URL.revokeObjectURL(image.src), { once: true });
    section.append(image);
  } catch (error) {
    section.append(messageElement(error.message, "error"));
  }
  detail.append(section);
}

function text(value, tag = null) {
  if (!tag) return document.createTextNode(value);
  const element = document.createElement(tag);
  element.textContent = value;
  return element;
}

function messageElement(value, className) {
  const element = document.createElement("div");
  element.className = className;
  element.textContent = value;
  return element;
}

function formatTime(value) {
  return new Intl.DateTimeFormat("zh-CN", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

function formatNumber(value) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function formatBudget(usage) {
  const requestText = usage.daily_request_limit == null
    ? "请求不限"
    : `${formatNumber(usage.daily_requests_used)} / ${formatNumber(usage.daily_request_limit)} 请求`;
  if (usage.daily_cost_budget_microusd == null) return `${requestText} · 成本不限`;
  const committed = `$${(usage.daily_cost_committed_microusd / 1_000_000).toFixed(4)}`;
  const budget = `$${(usage.daily_cost_budget_microusd / 1_000_000).toFixed(4)}`;
  return `${requestText} · ${committed} / ${budget}${usage.budget_exceeded ? " · 已超限" : ""}`;
}

function versionQualityText(byRelease, byVersion) {
  const releases = Object.entries(byRelease || {}).sort(([left], [right]) =>
    right.localeCompare(left, "zh-CN", { numeric: true })
  );
  if (releases.length) {
    return releases.map(([version, bucket]) =>
      `${version} · ${(bucket.negative_rate * 100).toFixed(1)}% 负反馈 · ${bucket.total} 条`
    ).join("；");
  }
  const versions = Object.entries(byVersion || {}).sort(([left], [right]) =>
    right.localeCompare(left, "zh-CN", { numeric: true })
  );
  if (!versions.length) return "暂无反馈";
  const [version, bucket] = versions[0];
  return `${version} · ${(bucket.negative_rate * 100).toFixed(1)}% 负反馈`;
}

function statusLabel(value) {
  return ({
    new: "新反馈",
    triaged: "已分类",
    reproduced: "已复现",
    planned: "已计划",
    fixed: "已修复",
    released: "已发布",
    rejected: "已拒绝"
  })[value] || value;
}

function releaseStatusLabel(value) {
  return ({ draft: "草稿", published: "已发布", superseded: "已替代", rolled_back: "已回滚" })[value] || value;
}

function categoryLabel(value) {
  return ({ quality: "结果质量", bug: "Bug", performance: "性能", feature: "功能建议", other: "其他" })[value] || value;
}
