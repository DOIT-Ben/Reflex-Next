const state = { token: "", selectedId: "", items: [] };
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

document.querySelector("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.token = tokenInput.value;
  tokenInput.value = "";
  await Promise.all([loadFeedback(), loadOperations()]);
});

document.querySelector("#filters").addEventListener("submit", async (event) => {
  event.preventDefault();
  await loadFeedback();
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
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
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
    qualityVersion.textContent = versionQualityText(quality.by_version);
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
  head.append(title, status);
  detail.append(head, metadata(item));
  appendSection("反馈描述", item.message || "未填写");
  appendSection("期望结果", item.expected_output || "未填写");
  if (item.prompt_text) appendSection("授权附加的提示词", item.prompt_text);
  if (item.result_text) appendSection("授权附加的结果", item.result_text);
  if (item.screenshot_url) void appendScreenshot(item.screenshot_url);
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

function versionQualityText(byVersion) {
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

function categoryLabel(value) {
  return ({ quality: "结果质量", bug: "Bug", performance: "性能", feature: "功能建议", other: "其他" })[value] || value;
}
