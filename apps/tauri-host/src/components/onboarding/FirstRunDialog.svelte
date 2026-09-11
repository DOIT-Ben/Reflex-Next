<script lang="ts">
  import { onMount, tick } from "svelte";
  import type { ActivationRoute } from "../../domain/activationState";
  import { translator } from "../../domain/i18nStore";
  import BaseButton from "../ui/BaseButton.svelte";
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
        <BaseButton variant="primary" onclick={() => void onContinue()}>
          {translate("开始处理第一段文本")}
        </BaseButton>
      </div>
    {:else if selectedRoute === "byok"}
      <div class="ready-state">
        <strong>{translate("请先配置 API Key")}</strong>
        <p>{translate("密钥只保存在 Windows 凭据管理器。")}</p>
        <BaseButton variant="primary" onclick={() => void onOpenSettings()}>
          {translate("打开设置")}
        </BaseButton>
      </div>
    {:else}
      <div class="ready-state">
        <strong>{translate("免费试用暂不可用，请选择自备 API Key。")}</strong>
        <BaseButton variant="primary" onclick={() => void onChoose("byok")}>
          {translate("使用自己的 API Key")}
        </BaseButton>
      </div>
    {/if}

    {#if notice}
      <p class="notice" role="status">{notice}</p>
    {/if}

    <BaseButton variant="quiet" onclick={() => void onLater()}>{translate("稍后设置")}</BaseButton>
  </div>
</DialogShell>

<style>
  .activation-body {
    color: var(--text, #202535);
  }

  .eyebrow, .intro, .ready-state p, .notice { margin: 0; }
  .eyebrow { color: var(--accent, #5065c7); font-size: var(--font-meta); font-weight: 700; letter-spacing: .08em; text-transform: uppercase; }
  .intro { margin-top: 7px; color: var(--muted, #697386); font-size: var(--font-body); line-height: 1.6; }
  .route-list { display: grid; gap: 9px; margin-top: 22px; }
  .route-card { display: flex; min-height: 82px; flex-direction: column; align-items: flex-start; gap: 5px; padding: 15px; color: var(--text, #202535); background: var(--surface, #fff); border: 1px solid var(--line, #e1e6ee); border-radius: 10px; font: inherit; text-align: left; cursor: pointer; }
  .route-card:hover, .route-card:focus-visible { border-color: var(--accent, #5065c7); background: var(--accent-soft, #eef1ff); }
  .route-card strong { font-size: var(--font-body); }
  .route-card span { color: var(--muted, #697386); font-size: var(--font-meta); line-height: 1.5; }
  .primary-route { border-color: color-mix(in srgb, var(--accent, #5065c7) 42%, var(--line, #e1e6ee)); }
  .ready-state { display: grid; gap: 10px; margin-top: 22px; padding: 16px; background: var(--accent-soft, #eef1ff); border-radius: 10px; }
  .ready-state strong { font-size: var(--font-body); }
  .ready-state p { color: var(--muted, #697386); font-size: var(--font-meta); line-height: 1.55; }
  .notice { margin-top: 12px; color: var(--muted, #697386); font-size: var(--font-meta); line-height: 1.5; }
  button:focus-visible { outline: 2px solid var(--accent, #5065c7); outline-offset: 2px; }
</style>
