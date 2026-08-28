<script lang="ts">
  import ImageOff from "@lucide/svelte/icons/image-off";
  import Send from "@lucide/svelte/icons/send";
  import X from "@lucide/svelte/icons/x";
  import SelectField from "../ui/SelectField.svelte";

  import type {
    FeedbackCategory,
    FeedbackFormValue,
    FeedbackScreenshot,
    FeedbackSentiment
  } from "../../domain/feedbackBridge";

  export let sentiment: FeedbackSentiment;
  export let screenshot: FeedbackScreenshot | null = null;
  export let captureNotice: string | null = null;
  export let improvementConsent = false;
  export let busy = false;
  export let notice: string | null = null;
  export let translate: (source: string, values?: Record<string, string | number>) => string;
  export let onClose: () => void;
  export let onRemoveScreenshot: () => void;
  export let onSubmit: (value: FeedbackFormValue) => void | Promise<void>;

  let category: FeedbackCategory = "quality";
  let message = "";
  let expectedOutput = "";
  let contact = "";
  let includePrompt = false;
  let includeResult = false;
  let includeScreenshot = false;
  $: categoryOptions = [
    { value: "quality", label: translate("结果质量") },
    { value: "bug", label: translate("功能异常") },
    { value: "performance", label: translate("速度与性能") },
    { value: "feature", label: translate("功能建议") },
    { value: "other", label: translate("其他") }
  ];

  $: if (!improvementConsent) {
    includePrompt = false;
    includeResult = false;
  }

  $: screenshotUrl = screenshot
    ? `data:${screenshot.media_type};base64,${screenshot.data_base64}`
    : "";

  function submit() {
    if (busy) return;
    void onSubmit({
      category,
      message: message.trim(),
      expectedOutput: expectedOutput.trim(),
      contact: contact.trim(),
      includePrompt,
      includeResult,
      includeScreenshot: includeScreenshot && screenshot !== null
    });
  }
</script>

<div class="feedback-layer" role="presentation">
  <button class="feedback-backdrop" type="button" aria-label={translate("关闭反馈")} disabled={busy} onclick={onClose}></button>
  <div class="feedback-dialog" role="dialog" aria-modal="true" aria-labelledby="feedback-title">
    <header>
      <div>
        <span class:negative={sentiment === "negative"}>{translate(sentiment === "negative" ? "结果不满意" : "结果满意")}</span>
        <h2 id="feedback-title">{translate("提交反馈")}</h2>
      </div>
      <button class="icon-button" type="button" aria-label={translate("关闭反馈")} title={translate("关闭")} disabled={busy} onclick={onClose}>
        <X size={17} strokeWidth={2} />
      </button>
    </header>

    <div class="feedback-content">
      <div class="feedback-fields">
        <label>
          <span>{translate("反馈类型")}</span>
          <SelectField
            value={category}
            options={categoryOptions}
            ariaLabel={translate("反馈类型")}
            disabled={busy}
            onValueChange={(value) => (category = value as FeedbackCategory)}
          />
        </label>
        <label>
          <span>{translate("具体问题")}</span>
          <textarea bind:value={message} maxlength="4000" rows="5" placeholder={translate("描述发生了什么…")} disabled={busy}></textarea>
        </label>
        <label>
          <span>{translate("期望结果")}</span>
          <textarea bind:value={expectedOutput} maxlength="10000" rows="3" placeholder={translate("你希望得到怎样的结果？")} disabled={busy}></textarea>
        </label>
        <label>
          <span>{translate("联系方式（可选）")}</span>
          <input bind:value={contact} maxlength="320" placeholder={translate("邮箱或其他联系方式")} disabled={busy} />
        </label>
      </div>

      <div class="feedback-evidence">
        <div class="evidence-head">
          <strong>{translate("应用截图预览")}</strong>
          {#if screenshot}
            <button type="button" title={translate("移除截图")} aria-label={translate("移除截图")} disabled={busy} onclick={() => { includeScreenshot = false; onRemoveScreenshot(); }}>
              <ImageOff size={15} strokeWidth={2} />
            </button>
          {/if}
        </div>
        {#if screenshot}
          <img src={screenshotUrl} alt={translate("即将随反馈提交的 Reflex 应用截图")} />
        {:else}
          <div class="screenshot-empty">{translate("未附加截图")}</div>
        {/if}
        {#if captureNotice}<p class="notice">{translate(captureNotice)}</p>{/if}
        <div class="privacy-options">
          <label><input type="checkbox" bind:checked={includePrompt} disabled={busy || !improvementConsent} />{translate("附加本次输入")}</label>
          <label><input type="checkbox" bind:checked={includeResult} disabled={busy || !improvementConsent} />{translate("附加本次结果")}</label>
          {#if screenshot}
            <label><input type="checkbox" bind:checked={includeScreenshot} disabled={busy} />{translate("附加应用截图")}</label>
          {/if}
        </div>
        <p class="privacy-note">
          {translate(!improvementConsent ? "附加输入和结果前，请先在设置的安全与隐私中开启产品改进计划。" : "仅勾选的内容会随反馈发送。")}
          {translate("API Key 和无关剪贴板内容不会上传。")}
        </p>
      </div>
    </div>

    <footer>
      <span class:error={notice?.includes("失败")}>{notice ? translate(notice) : ""}</span>
      <div>
        <button class="outline" type="button" disabled={busy} onclick={onClose}>{translate("取消")}</button>
        <button class="primary" type="button" disabled={busy || (sentiment === "negative" && category === "other" && !message.trim())} onclick={submit}>
          <Send size={15} strokeWidth={2} />{translate(busy ? "正在发送" : "发送反馈")}
        </button>
      </div>
    </footer>
  </div>
</div>

<style>
  .feedback-layer { position: absolute; inset: 0; z-index: 30; display: grid; place-items: center; padding: 18px; }
  .feedback-backdrop { position: absolute; inset: 0; width: 100%; height: 100%; background: rgb(24 31 48 / 28%); border: 0; }
  .feedback-dialog { position: relative; display: flex; width: min(760px, 100%); max-height: min(620px, calc(100% - 12px)); flex-direction: column; overflow: hidden; color: var(--text); background: var(--surface); border: 1px solid var(--line-strong); border-radius: 8px; box-shadow: 0 20px 54px rgb(18 24 38 / 24%); }
  header, footer { display: flex; flex: 0 0 auto; align-items: center; justify-content: space-between; gap: 14px; padding: 14px 16px; }
  header { border-bottom: 1px solid var(--line); }
  header div { display: flex; align-items: baseline; gap: 10px; }
  header span { color: #287a52; font-size: var(--font-meta); font-weight: 650; }
  header span.negative { color: var(--danger); }
  h2 { margin: 0; font-size: var(--font-title); }
  .icon-button, .evidence-head button { display: grid; width: 32px; height: 32px; place-items: center; padding: 0; color: var(--muted); background: transparent; border: 0; border-radius: 50%; }
  .icon-button:hover, .evidence-head button:hover { color: var(--text); background: var(--accent-soft); }
  .feedback-content { display: grid; min-height: 0; grid-template-columns: minmax(0, 1.08fr) minmax(260px, .92fr); overflow: auto; }
  .feedback-fields, .feedback-evidence { display: flex; min-width: 0; flex-direction: column; gap: 12px; padding: 16px; }
  .feedback-evidence { background: color-mix(in srgb, var(--window) 74%, var(--surface)); border-left: 1px solid var(--line); }
  label { display: grid; gap: 6px; color: var(--muted); font-size: var(--font-meta); }
  input, textarea { width: 100%; color: var(--text); background: var(--surface); border: 1px solid var(--line-strong); border-radius: 6px; }
  input { min-height: 36px; padding: 0 10px; }
  textarea { padding: 9px 10px; resize: vertical; }
  input:focus, textarea:focus { outline: 2px solid color-mix(in srgb, var(--accent) 26%, transparent); border-color: var(--accent); }
  .evidence-head { display: flex; min-height: 32px; align-items: center; justify-content: space-between; }
  .evidence-head strong { font-size: var(--font-body); }
  img, .screenshot-empty { width: 100%; aspect-ratio: 16 / 10; border: 1px solid var(--line); border-radius: 6px; }
  img { object-fit: contain; background: #fff; }
  .screenshot-empty { display: grid; place-items: center; color: var(--muted); background: var(--window); font-size: var(--font-meta); }
  .privacy-options { display: grid; gap: 7px; }
  .privacy-options label { display: flex; align-items: center; gap: 7px; color: var(--text); }
  .privacy-options input { width: 15px; min-height: 15px; }
  .privacy-note, .notice { margin: 0; color: var(--muted); font-size: var(--font-meta); line-height: 1.45; }
  footer { border-top: 1px solid var(--line); }
  footer > span { min-width: 0; color: #287a52; font-size: var(--font-meta); }
  footer > span.error { color: var(--danger); }
  footer > div { display: flex; gap: 8px; }
  footer button { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 6px; padding: 0 14px; border-radius: 6px; }
  .outline { color: var(--text); background: var(--surface); border: 1px solid var(--line-strong); }
  .primary { color: #fff; background: var(--accent); border: 1px solid var(--accent); }
  button:disabled { cursor: default; opacity: .55; }
  @media (max-width: 680px) {
    .feedback-layer { padding: 8px; }
    .feedback-dialog { max-height: calc(100% - 4px); }
    .feedback-content { grid-template-columns: 1fr; }
    .feedback-evidence { border-top: 1px solid var(--line); border-left: 0; }
    header div { align-items: flex-start; flex-direction: column; gap: 3px; }
    footer { align-items: flex-start; flex-direction: column; }
    footer > div { width: 100%; justify-content: flex-end; }
  }
</style>
