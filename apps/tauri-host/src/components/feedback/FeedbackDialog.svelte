<script lang="ts">
  import { Button } from "@/components/ui/button";
  import ImageOff from "@lucide/svelte/icons/image-off";
  import Send from "@lucide/svelte/icons/send";
  import DialogShell from "../ui/DialogShell.svelte";
  import AppSelect from "@/components/ui/AppSelect.svelte";
  import { translator } from "../../domain/i18nStore";

  import type {
    FeedbackCategory,
    FeedbackFormValue,
    FeedbackScreenshot,
    FeedbackSentiment
  } from "../../domain/feedbackBridge";

  interface Props {
    sentiment: FeedbackSentiment;
    screenshot: FeedbackScreenshot | null;
    captureNotice: string | null;
    improvementConsent: boolean;
    busy: boolean;
    notice: string | null;
    onClose: () => void;
    onRemoveScreenshot: () => void;
    onSubmit: (value: FeedbackFormValue) => void | Promise<void>;
  }

  let {
    sentiment,
    screenshot = null,
    captureNotice = null,
    improvementConsent = false,
    busy = false,
    notice = null,
    onClose,
    onRemoveScreenshot,
    onSubmit
  }: Props = $props();

  let translate = $derived($translator);
  let category: FeedbackCategory = "quality";
  let message = "";
  let expectedOutput = "";
  let contact = "";
  let includePrompt = false;
  let includeResult = false;
  let includeScreenshot = false;
  let categoryOptions = $derived([
    { value: "quality", label: translate("结果质量") },
    { value: "bug", label: translate("功能异常") },
    { value: "performance", label: translate("速度与性能") },
    { value: "feature", label: translate("功能建议") },
    { value: "other", label: translate("其他") }
  ]);

  $effect(() => {
    if (!improvementConsent) {
      includePrompt = false;
      includeResult = false;
    }
  });

  let screenshotUrl = $derived(
    screenshot
      ? `data:${screenshot.media_type};base64,${screenshot.data_base64}`
      : ""
  );

  function requestClose() {
    if (!busy) onClose();
  }

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

<DialogShell
  title={translate("提交反馈")}
  description={translate(sentiment === "negative" ? "结果不满意" : "结果满意")}
  z={30}
  closeLabel={translate("关闭反馈")}
  onClose={requestClose}
  closeOnBackdrop={true}
  size="lg"
>
  <div class="feedback-content">
    <div class="feedback-fields">
      <label>
        <span>{translate("反馈类型")}</span>
        <AppSelect
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
          <Button variant="ghost" size="icon-sm" title={translate("移除截图")} aria-label={translate("移除截图")} disabled={busy} onclick={() => { includeScreenshot = false; onRemoveScreenshot(); }}>
            <ImageOff size={15} strokeWidth={2} />
          </Button>
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

  <footer slot="footer">
    <div class="feedback-footer-inner">
      <span class:error={notice?.includes("失败")}>{notice ? translate(notice) : ""}</span>
      <div class="feedback-footer-actions">
        <Button variant="outline" disabled={busy} onclick={onClose}>{translate("取消")}</Button>
        <Button size="sm" disabled={busy || (sentiment === "negative" && category === "other" && !message.trim())} onclick={submit}>
          <Send size={15} strokeWidth={2} />{translate(busy ? "正在发送" : "发送反馈")}
        </Button>
      </div>
    </div>
  </footer>
</DialogShell>

<style>
  .feedback-content { display: grid; min-height: 0; grid-template-columns: minmax(0, 1.08fr) minmax(260px, .92fr); overflow: auto; }
  .feedback-fields, .feedback-evidence { display: flex; min-width: 0; flex-direction: column; gap: 12px; padding: 16px; }
  .feedback-fields { padding-left: 0; }
  .feedback-evidence { background: color-mix(in srgb, var(--window) 74%, var(--surface)); border-left: 1px solid var(--line); }
  label { display: grid; gap: 6px; color: var(--muted); font-size: var(--font-meta);  line-height: var(--leading-meta); }
  input, textarea { width: 100%; color: var(--text); background: var(--surface); border: 1px solid var(--line-strong); border-radius: 8px; }
  input { min-height: 36px; padding: 0 10px; }
  textarea { padding: 9px 10px; resize: vertical; }
  input:focus, textarea:focus { outline: 2px solid color-mix(in srgb, var(--accent) 26%, transparent); border-color: var(--accent); }
  .evidence-head { display: flex; min-height: 32px; align-items: center; justify-content: space-between; }
  .evidence-head button { display: grid; width: 32px; height: 32px; place-items: center; padding: 0; color: var(--muted); background: transparent; border: 0; border-radius: 50%; }
  .evidence-head button:hover { color: var(--text); background: var(--accent-soft); }
  .evidence-head strong { font-size: var(--font-body);  line-height: var(--leading-body); }
  img, .screenshot-empty { width: 100%; aspect-ratio: 16 / 10; border: 1px solid var(--line); border-radius: 12px; }
  img { object-fit: contain; background: #fff; }
  .screenshot-empty { display: grid; place-items: center; color: var(--muted); background: var(--window); font-size: var(--font-meta);  line-height: var(--leading-meta); }
  .privacy-options { display: grid; gap: 7px; }
  .privacy-options label { display: flex; align-items: center; gap: 7px; color: var(--text); }
  .privacy-options input { width: 15px; min-height: 15px; }
  .privacy-note, .notice { margin: 0; color: var(--muted); font-size: var(--font-meta); line-height: var(--leading-meta); }
  .feedback-footer-inner { display: flex; flex: 1 1 auto; align-items: center; justify-content: space-between; gap: 14px; min-width: 0; }
  .feedback-footer-inner > span { min-width: 0; color: #287a52; font-size: var(--font-meta);  line-height: var(--leading-meta); }
  .feedback-footer-inner > span.error { color: var(--danger); }
  .feedback-footer-actions { display: flex; flex: 0 0 auto; gap: 8px; }
  .feedback-footer-actions button { display: inline-flex; min-height: 36px; align-items: center; justify-content: center; gap: 6px; padding: 0 14px; border-radius: 8px; }
  .outline { color: var(--text); background: var(--surface); border: 1px solid var(--line-strong); }
  .primary { color: #fff; background: var(--accent); border: 1px solid var(--accent); }
  button:disabled { cursor: default; opacity: .55; }
  @media (max-width: 680px) {
    .feedback-content { grid-template-columns: 1fr; }
    .feedback-fields { padding-right: 0; }
    .feedback-evidence { border-top: 1px solid var(--line); border-left: 0; }
    .feedback-footer-inner { align-items: flex-start; flex-direction: column; }
    .feedback-footer-actions { width: 100%; justify-content: flex-end; }
  }
</style>
