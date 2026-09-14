<script lang="ts">
  import { onMount } from "svelte";
  import {
    createDefaultCoreBridge,
    createDemoCoreBridge,
    type CoreBridge,
    type TauriHostApi
  } from "./domain/coreBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";
  import { applyDocumentTheme, type ThemeChoice } from "./domain/themeApply";
  import { Button } from "@/components/ui/button";
  import { Textarea } from "@/components/ui/textarea";
  import X from "@lucide/svelte/icons/x";
  import SegmentedControl from "@/components/ui/SegmentedControl.svelte";
  import { createSettingsApi, type AppConfig } from "./domain/settingsApi";
  import {
    applyCoreEvent,
    createDraftRequest,
    createInitialSession,
    type OptimizeMode,
    type OptimizeStyle,
    type OutputLanguage
  } from "./domain/reflexSession";
  import {
    createClipboardReader,
    createClipboardWriter,
    readClipboardText,
    writeClipboardText
  } from "./domain/clipboardBridge";

  const modes: Array<{ id: OptimizeMode; label: string }> = [
    { id: "content", label: "内容优化" },
    { id: "prompt", label: "提示词生成" }
  ];
  const styles: Array<{ id: OptimizeStyle; label: string }> = [
    { id: "concise", label: "简洁" },
    { id: "balanced", label: "平衡" },
    { id: "detailed", label: "详细" },
    { id: "creative", label: "创意" }
  ];

  let host: TauriHostApi | null = null;
  let bridge: CoreBridge | null = null;
  let config: AppConfig | null = null;
  let clipboardReader: ReturnType<typeof createClipboardReader> | null = null;
  let clipboardWriter: ReturnType<typeof createClipboardWriter> | null = null;
  let lastAutoFilledClipboard = "";

  let inputText = $state("");
  let mode = $state<OptimizeMode>("content");
  let style = $state<OptimizeStyle>("balanced");
  let session = $state(createInitialSession());
  let running = $state(false);
  let copied = $state(false);
  let notice = $state<string | null>(null);
  let dark = $state(false);
  let inputEl = $state<HTMLTextAreaElement | null>(null);

  let busy = $derived(running);
  let output = $derived(session.output);
  let failed = $derived(session.phase === "failed");
  let complete = $derived(session.phase === "complete");

  onMount(() => {
    document.body.classList.add("panel-body");
    return () => {
      document.body.classList.remove("panel-body");
    };
  });

  void initialize();

  async function initialize() {
    host = await createTauriHostApi();
    const systemDark =
      typeof window.matchMedia === "function" && window.matchMedia("(prefers-color-scheme: dark)").matches;
    if (host) {
      clipboardReader = createClipboardReader(host);
      clipboardWriter = createClipboardWriter(host);
      try {
        config = await createSettingsApi(host).loadConfig();
      } catch {
        config = null;
      }
      mode = config?.mode ?? mode;
      style = config?.style ?? style;
      const initialized = await createDefaultCoreBridge(host).catch(() => null);
      bridge = initialized?.runtimeAvailable
        ? initialized.bridge
        : (initialized?.bridge ?? (import.meta.env.DEV ? createDemoCoreBridge() : null));
      // Warm the Runtime so the first panel optimization skips startup cost.
      void host.invoke("runtime_warmup").catch(() => undefined);
    } else if (import.meta.env.DEV) {
      bridge = createDemoCoreBridge();
    }
    dark = config?.theme === "dark" || (config?.theme !== "light" && systemDark);
    applyDocumentTheme((config?.theme ?? (systemDark ? "dark" : "light")) as ThemeChoice);
    window.addEventListener("focus", onPanelFocus);
    window.addEventListener("keydown", onPanelKeydown);
    await onPanelFocus();
    inputEl?.focus();
  }

  async function onPanelFocus() {
    if (!clipboardReader || busy) return;
    const result = await readClipboardText(clipboardReader);
    if (!result.ok || result.text === lastAutoFilledClipboard) return;
    lastAutoFilledClipboard = result.text;
    if (result.text !== inputText) {
      inputText = result.text;
      session = createInitialSession();
      copied = false;
      notice = null;
    }
    inputEl?.focus();
  }

  function onPanelKeydown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.preventDefault();
      void hidePanel();
      return;
    }
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      void run();
    }
  }

  async function hidePanel() {
    await host?.invoke("hide_panel_window").catch(() => undefined);
  }

  async function run() {
    if (busy || !inputText.trim() || !bridge) return;
    const controller = new AbortController();
    session = { ...createInitialSession(), phase: "running", statusMessage: "正在优化" };
    copied = false;
    notice = null;
    running = true;
    const request = createDraftRequest(inputText, language());
    request.mode = mode;
    request.style = style;
    request.scene_policy = "auto";
    request.provider = config?.provider ?? null;
    request.model = config?.model ?? null;
    try {
      for await (const event of bridge.optimize(request, { signal: controller.signal })) {
        session = applyCoreEvent(session, event);
      }
    } catch {
      session = {
        ...session,
        phase: "failed",
        statusMessage: "生成失败",
        errorMessage: "优化中断，请重试。"
      };
    } finally {
      running = false;
      if (session.phase === "complete") {
        await autoReplaceClipboard();
      }
    }
  }

  function language(): OutputLanguage {
    return config?.language === "en-US" ? "en-US" : "zh-CN";
  }

  async function autoReplaceClipboard() {
    // Only silently replace the clipboard after the user has confirmed the
    // auto-replace policy; otherwise copying stays an explicit action.
    if (config?.clipboard_policy !== "auto_replace" || config?.clipboard_replace_confirmed !== true) {
      return;
    }
    await copyResult();
  }

  async function copyResult() {
    if (!clipboardWriter || !output.trim()) return;
    const result = await writeClipboardText(clipboardWriter, output);
    if (result.ok) {
      copied = true;
      notice = "结果已复制到剪贴板。";
    } else {
      notice = result.message;
    }
  }

  function setMode(value: OptimizeMode) {
    mode = value;
  }

  function setStyle(value: OptimizeStyle) {
    style = value;
  }
</script>

<div class="panel" class:dark>
  <header class="panel-header">
    <span class="panel-title">快捷优化</span>
    <span class="panel-status">
      {#if busy}{session.statusMessage}{:else if complete}已完成{session.elapsedSeconds !== null ? ` · ${session.elapsedSeconds}s` : ""}{:else}Alt+Q 展开 · Esc 收起{/if}
    </span>
    <Button variant="ghost" size="icon-sm" class="panel-close" title="隐藏面板 (Esc)" aria-label="隐藏面板" onclick={() => void hidePanel()}>
      <X size={15} strokeWidth={2} />
    </Button>
  </header>

  <Textarea
    bind:ref={inputEl}
    bind:value={inputText}
    class="panel-input focus-visible:ring-[2px] focus-visible:ring-ring/40"
    placeholder="粘贴或输入要优化的文字，Ctrl+Enter 直接优化"
    rows={4}
    disabled={busy}
  />

  <div class="panel-controls">
    <SegmentedControl
      options={modes.map((item) => ({ id: item.id, label: item.label }))}
      value={mode}
      disabled={busy}
      ariaLabel="优化模式"
      onValueChange={(value) => setMode(value)}
    />
    <SegmentedControl
      options={styles.map((item) => ({ id: item.id, label: item.label }))}
      value={style}
      disabled={busy}
      ariaLabel="输出风格"
      onValueChange={(value) => setStyle(value)}
    />
    <Button class="panel-run" size="sm" disabled={busy || !inputText.trim()} onclick={() => void run()}>
      {busy ? "优化中…" : "优化"}
    </Button>
  </div>

  {#if session.detectedScene}
    <div class="panel-scene">场景：{session.detectedScene.scene}（{Math.round(session.detectedScene.confidence * 100)}%）</div>
  {/if}

  {#if output || failed}
    <div class="panel-result" class:failed>
      {#if failed}
        <span class="panel-error">{session.errorMessage ?? "生成失败，请重试。"}</span>
      {:else}
        <pre class="panel-output">{output}</pre>
      {/if}
    </div>
    {#if complete}
      <div class="panel-actions">
        <Button class="panel-copy" variant={copied ? "secondary" : "outline"} size="sm" onclick={() => void copyResult()}>
          {copied ? "已复制" : "复制结果"}
        </Button>
        <span class="panel-hint">Ctrl+Enter 重新优化 · Esc 隐藏</span>
      </div>
    {/if}
  {/if}

  {#if notice}
    <div class="panel-notice">{notice}</div>
  {/if}
</div>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 10px;
    box-sizing: border-box;
    height: 100vh;
    padding: 12px;
    color: hsl(var(--foreground));
    background: hsl(var(--background));
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
    box-shadow: 0 18px 48px rgb(20 24 34 / 18%);
    font-family: inherit;
  }

  .panel-header {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .panel-title {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    font-weight: 600;
  }

  .panel-status {
    flex: 1;
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    text-align: right;
  }

  .panel-controls {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 8px;
  }

  .panel-scene {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  .panel-result {
    flex: 1;
    min-height: 48px;
    padding: 10px;
    overflow: auto;
    background: hsl(var(--muted));
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
  }

  .panel-result.failed {
    border-color: hsl(var(--destructive, 0 84% 60%));
  }

  .panel-output {
    margin: 0;
    font: inherit;
    font-size: var(--font-body);
    line-height: var(--leading-prose);
    white-space: pre-wrap;
    word-break: break-word;
  }

  .panel-error {
    color: hsl(var(--destructive, 0 84% 60%));
    font-size: var(--font-body);
    line-height: var(--leading-body);
  }

  .panel-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .panel-hint {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  .panel-notice {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }
</style>
