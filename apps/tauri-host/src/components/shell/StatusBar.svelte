<script lang="ts">
  import type { StatusTone } from "./types";

  interface Props {
    message?: string;
    tone?: StatusTone;
    inputCount?: number;
    countLabel?: string;
    languageLabel?: string;
    themeLabel?: string;
    versionLabel?: string;
    ariaLabel?: string;
  }

  let {
    message = "就绪",
    tone = "idle",
    inputCount = 0,
    countLabel = "字",
    languageLabel = "中文",
    themeLabel = "系统",
    versionLabel = "",
    ariaLabel = "应用状态"
  }: Props = $props();
</script>

<footer class="status-bar" aria-label={ariaLabel}>
  <span class="status-message" data-tone={tone} role="status" aria-live="polite" aria-atomic="true">
    <span class="status-dot" aria-hidden="true"></span>
    <span class="message-text">{message}</span>
  </span>

  <span class="metadata" aria-label="文档信息">
    <span class="count">{inputCount.toLocaleString()} {countLabel}</span>
    <span class="divider" aria-hidden="true">·</span>
    <span>{languageLabel}</span>
    <span class="divider" aria-hidden="true">·</span>
    <span class="theme">{themeLabel}</span>
    {#if versionLabel}
      <span class="divider version-divider" aria-hidden="true">·</span>
      <span class="version">{versionLabel}</span>
    {/if}
  </span>
</footer>

<style>
  .status-bar {
    container-type: inline-size;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    width: 100%;
    min-width: 0;
    height: 24px;
    padding: 0 10px;
    color: var(--muted, #697386);
    background: var(--surface, #fff);
    border-top: 1px solid var(--line, #e1e6ee);
    box-sizing: border-box;
    font-size: var(--font-meta);
    line-height: 1;
    user-select: none;
  }

  .status-message,
  .metadata {
    display: flex;
    align-items: center;
  }

  .status-message {
    min-width: 0;
    gap: 6px;
  }

  .message-text {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .status-dot {
    flex: 0 0 auto;
    width: 6px;
    height: 6px;
    background: #8b95a7;
    border-radius: 50%;
  }

  .status-message[data-tone="working"] .status-dot {
    background: var(--accent, #5065c7);
    animation: status-pulse 1.4s ease-in-out infinite;
  }

  .status-message[data-tone="success"] .status-dot {
    background: #2f9e62;
  }

  .status-message[data-tone="warning"] .status-dot {
    background: #d08724;
  }

  .status-message[data-tone="error"] {
    color: #b42318;
  }

  .status-message[data-tone="error"] .status-dot {
    background: #cf4b4b;
  }

  .metadata {
    flex: 0 0 auto;
    gap: 6px;
    white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }

  .divider {
    color: color-mix(in srgb, var(--muted, #697386) 38%, transparent);
  }

  @keyframes status-pulse {
    50% {
      opacity: 0.42;
      transform: scale(0.82);
    }
  }

  @container (max-width: 620px) {
    .theme,
    .version,
    .version-divider {
      display: none;
    }
  }

  @container (max-width: 460px) {
    .metadata > :not(.count) {
      display: none;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .status-message[data-tone="working"] .status-dot {
      animation: none;
    }
  }
</style>
