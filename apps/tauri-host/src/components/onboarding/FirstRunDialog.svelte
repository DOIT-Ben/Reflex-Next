<script lang="ts">
  import { onMount, tick } from "svelte";
  import type { ActivationRoute } from "../../domain/activationState";
  import { translator } from "../../domain/i18nStore";
  import { Button } from "@/components/ui/button";
  import DialogShell from "../ui/DialogShell.svelte";

  export let routes: ReadonlyArray<ActivationRoute> = ["byok"];
  export let selectedRoute: ActivationRoute | null = null;
  export let providerReady = false;
  export let providerLabel = "";
  export let notice = "";
  export let onChoose: (route: ActivationRoute) => void | Promise<void> = () => undefined;
  export let onOpenSettings: () => void | Promise<void> = () => undefined;
  export let onContinue: () => void | Promise<void> = () => undefined;
  export let onLater: () => void | Promise<void> = () => undefined;

  $: translate = $translator;
  $: cloudAvailable = routes.includes("cloud");

  let body: HTMLElement;
  let restoreFocus: HTMLElement | null = null;
  const focusableSelector =
    'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])';

  function focusableElements(): HTMLElement[] {
    return Array.from(body?.querySelectorAll<HTMLElement>(focusableSelector) ?? []).filter(
      (element) => element.offsetWidth > 0 || element.offsetHeight > 0
    );
  }

  function canRestoreFocus(element: HTMLElement | null): element is HTMLElement {
    return Boolean(
      element?.isConnected &&
        element !== document.body &&
        element !== document.documentElement &&
        !element.closest("[inert]")
    );
  }

  onMount(() => {
    restoreFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    void tick().then(() => focusableElements()[0]?.focus());
    return () => {
      const fallback = document.querySelector<HTMLElement>("[data-dialog-focus-fallback]");
      if (canRestoreFocus(restoreFocus)) {
        restoreFocus.focus();
      } else {
        fallback?.focus();
      }
    };
  });
</script>

<DialogShell
  title={translate("开始使用 Reflex")}
  z={75}
  onClose={() => void onLater()}
  showClose={false}
  autofocusClose={false}
  size="sm"
>
  <div class="activation-body" bind:this={body}>
    <p class="eyebrow">Reflex</p>
    <p id="activation-intro" class="intro">{translate("先选择本次文本的处理方式。")}</p>

    {#if selectedRoute === null}
      <div class="route-list" aria-label={translate("接入方式")}>
        {#if cloudAvailable}
          <button class="route-card primary-route" type="button" on:click={() => void onChoose("cloud")}>
            <strong>{translate("使用免费试用")}</strong>
            <span>{translate("通过 Reflex Cloud 处理，可查看剩余额度。")}</span>
          </button>
        {/if}
        <button class="route-card" type="button" on:click={() => void onChoose("byok")}>
          <strong>{translate("使用自己的 API Key")}</strong>
          <span>{translate("密钥只保存在 Windows 凭据管理器。")}</span>
        </button>
      </div>
    {:else if providerReady}
      <div class="ready-state">
        <strong>{translate("已准备好")}</strong>
        <p>{translate("当前将使用 {provider}。", { provider: providerLabel })}</p>
        <Button onclick={() => void onContinue()}>
          {translate("开始处理第一段文本")}
        </Button>
      </div>
    {:else if selectedRoute === "byok"}
      <div class="ready-state">
        <strong>{translate("请先配置 API Key")}</strong>
        <p>{translate("密钥只保存在 Windows 凭据管理器。")}</p>
        <Button onclick={() => void onOpenSettings()}>
          {translate("打开设置")}
        </Button>
      </div>
    {:else}
      <div class="ready-state">
        <strong>{translate("免费试用暂不可用，请选择自备 API Key。")}</strong>
        <Button onclick={() => void onChoose("byok")}>
          {translate("使用自己的 API Key")}
        </Button>
      </div>
    {/if}

    {#if notice}
      <p class="notice" role="status">{notice}</p>
    {/if}

    <Button variant="ghost" size="sm" onclick={() => void onLater()}>{translate("稍后设置")}</Button>
  </div>
</DialogShell>

<style>
  .activation-body {
    color: hsl(var(--foreground));
  }

  .eyebrow,
  .intro,
  .ready-state p,
  .notice {
    margin: 0;
  }

  .eyebrow {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }

  .intro {
    margin-top: 8px;
    color: hsl(var(--muted-foreground));
    font-size: var(--font-body);
    line-height: var(--leading-prose);
  }

  .route-list {
    display: grid;
    gap: 8px;
    margin-top: 20px;
  }

  .route-card {
    display: flex;
    min-height: 72px;
    flex-direction: column;
    align-items: flex-start;
    gap: 4px;
    padding: 14px;
    color: hsl(var(--foreground));
    background: hsl(var(--muted) / 0.5);
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
    font: inherit;
    text-align: left;
    cursor: pointer;
    transition: background-color 160ms ease, border-color 160ms ease;
  }

  .route-card:hover,
  .route-card:focus-visible {
    background: hsl(var(--accent, 240 4.8% 95.9%));
    border-color: hsl(var(--ring, 210 100% 56%));
    outline: none;
  }

  .route-card strong {
    font-size: var(--font-body);
    line-height: var(--leading-body);
    font-weight: 600;
  }

  .route-card span {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  .ready-state {
    display: grid;
    gap: 10px;
    margin-top: 20px;
    padding: 14px;
    background: hsl(var(--muted));
    border: 1px solid hsl(var(--border));
    border-radius: 12px;
  }

  .ready-state strong {
    font-size: var(--font-body);
    line-height: var(--leading-body);
    font-weight: 600;
  }

  .ready-state p {
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }

  .notice {
    margin-top: 12px;
    color: hsl(var(--muted-foreground));
    font-size: var(--font-meta);
    line-height: var(--leading-meta);
  }
</style>
