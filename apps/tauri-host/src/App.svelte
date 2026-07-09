<script lang="ts">
  import { onMount } from "svelte";
  import {
    applyCoreEvent,
    createDraftRequest,
    createInitialSession,
    listPrototypeScenes,
    type OptimizeMode,
    type OptimizeStyle,
    type ScenePolicy
  } from "./domain/reflexSession";
  import { createDefaultCoreBridge } from "./domain/coreBridge";
  import { createTauriHostApi } from "./domain/tauriHostApi";

  type ViewName = "compose" | "settings" | "plugins";

  let coreBridge = createDefaultCoreBridge();
  const scenes = listPrototypeScenes();
  const styles: Array<{ id: OptimizeStyle; label: string }> = [
    { id: "concise", label: "简洁" },
    { id: "balanced", label: "平衡" },
    { id: "detailed", label: "详细" },
    { id: "creative", label: "创意" }
  ];
  const modes: Array<{ id: OptimizeMode; label: string }> = [
    { id: "content", label: "内容优化" },
    { id: "prompt", label: "提示词生成" }
  ];

  let view: ViewName = "compose";
  let inputText = "写一封求职邮件，语气真诚，突出我做过 AI 产品原型和本地工具链。";
  let mode: OptimizeMode = "content";
  let style: OptimizeStyle = "balanced";
  let scenePolicy: ScenePolicy = "auto";
  let selectedScene = "general";
  let provider = "MiniMax";
  let model = "abab6.5s-chat";
  let apiKey = "";
  let clipboardPolicy = true;
  let isRunning = false;
  let session = createInitialSession();
  let copyLabel = "复制";
  let activeRun: AbortController | null = null;

  const plugins = [
    {
      name: "MiniMax Provider",
      kind: "Provider",
      enabled: true,
      permissions: ["network", "secrets"]
    },
    {
      name: "Builtin Template Pack",
      kind: "模板包",
      enabled: true,
      permissions: []
    },
    {
      name: "L0 Rule Detector",
      kind: "场景识别",
      enabled: true,
      permissions: []
    },
    {
      name: "Semantic Detector",
      kind: "场景识别",
      enabled: false,
      permissions: ["model_cache"]
    }
  ];

  onMount(() => {
    void createTauriHostApi().then((host) => {
      if (host) {
        coreBridge = createDefaultCoreBridge(host);
      }
    });
  });

  $: canRun = inputText.trim().length > 0 && !isRunning;
  $: activeSceneLabel =
    scenes.find((scene) => scene.id === (session.detectedScene?.scene ?? selectedScene))?.label ??
    "通用";
  $: statusTone =
    session.phase === "failed" ? "danger" : session.phase === "complete" ? "done" : "live";

  async function runOptimization() {
    if (!canRun) return;
    isRunning = true;
    copyLabel = "复制";
    session = createInitialSession();
    const controller = new AbortController();
    activeRun = controller;

    const request = {
      ...createDraftRequest(inputText.trim()),
      mode,
      style,
      scene: scenePolicy === "manual" ? selectedScene : null,
      scene_policy: scenePolicy,
      provider,
      model
    };

    for await (const event of coreBridge.optimize(request, { signal: controller.signal })) {
      if (controller.signal.aborted) break;
      session = applyCoreEvent(session, event);
    }

    if (activeRun === controller) {
      activeRun = null;
      isRunning = false;
    }
  }

  function cancelRun() {
    activeRun?.abort();
    activeRun = null;
    isRunning = false;
    session = {
      ...session,
      phase: "idle",
      statusMessage: "已取消"
    };
  }

  async function copyResult() {
    if (!session.output) return;
    await navigator.clipboard?.writeText(session.output);
    copyLabel = "已复制";
    window.setTimeout(() => {
      copyLabel = "复制";
    }, 1200);
  }
</script>

<main class="shell">
  <aside class="rail" aria-label="Reflex navigation">
    <div class="brand">
      <span class="brand-mark">R</span>
      <span>Reflex</span>
    </div>

    <nav class="nav-stack">
      <button class:active={view === "compose"} on:click={() => (view = "compose")}>优化</button>
      <button class:active={view === "settings"} on:click={() => (view = "settings")}>设置</button>
      <button class:active={view === "plugins"} on:click={() => (view = "plugins")}>插件</button>
    </nav>

    <div class="rail-status" data-tone={statusTone}>
      <span></span>
      {session.statusMessage}
    </div>
  </aside>

  {#if view === "compose"}
    <section class="workspace" aria-label="Quick optimization panel">
      <section class="composer">
        <div class="panel-heading">
          <p>快捷浮窗</p>
          <h1>把当前这段话处理干净</h1>
        </div>

        <textarea bind:value={inputText} aria-label="原始文本"></textarea>

        <div class="control-grid">
          <label>
            <span>模式</span>
            <select bind:value={mode}>
              {#each modes as item}
                <option value={item.id}>{item.label}</option>
              {/each}
            </select>
          </label>
          <label>
            <span>风格</span>
            <select bind:value={style}>
              {#each styles as item}
                <option value={item.id}>{item.label}</option>
              {/each}
            </select>
          </label>
          <label>
            <span>场景</span>
            <select bind:value={selectedScene} disabled={scenePolicy !== "manual"}>
              {#each scenes as scene}
                <option value={scene.id}>{scene.label}</option>
              {/each}
            </select>
          </label>
          <label>
            <span>识别</span>
            <select bind:value={scenePolicy}>
              <option value="auto">自动</option>
              <option value="manual">手动</option>
              <option value="ask">询问</option>
            </select>
          </label>
        </div>

        <div class="action-row">
          <button class="primary" disabled={!canRun} on:click={runOptimization}>
            {isRunning ? "生成中" : "开始优化"}
          </button>
          <button class="ghost" disabled={!isRunning} on:click={cancelRun}>取消</button>
        </div>
      </section>

      <section class="result-panel">
        <div class="event-strip">
          <div>
            <span class="scene-pill">{activeSceneLabel}</span>
            <strong>{session.statusMessage}</strong>
          </div>
          <span>{provider} / {model}</span>
        </div>

        <div class="output" class:empty={!session.output && !session.errorMessage}>
          {#if session.errorMessage}
            <p class="error-text">{session.errorMessage}</p>
          {:else if session.output}
            <pre>{session.output}</pre>
          {:else}
            <p>等待 Core 事件流。</p>
          {/if}
        </div>

        <div class="timeline">
          {#each session.timeline as item, index}
            <div class="timeline-item">
              <span>{index + 1}</span>
              <p>{item.label}</p>
            </div>
          {/each}
        </div>

        <div class="action-row compact">
          <button class="secondary" disabled={!session.output} on:click={copyResult}>{copyLabel}</button>
          <button class="ghost" disabled={!session.output}>替换剪贴板</button>
          <button class="ghost" disabled={!session.output} on:click={runOptimization}>重新生成</button>
        </div>
      </section>
    </section>
  {:else if view === "settings"}
    <section class="settings-view" aria-label="Settings">
      <div class="panel-heading">
        <p>运行设置</p>
        <h1>默认模型与宿主权限</h1>
      </div>

      <div class="settings-grid">
        <label>
          <span>默认 Provider</span>
          <input bind:value={provider} />
        </label>
        <label>
          <span>默认模型</span>
          <input bind:value={model} />
        </label>
        <label>
          <span>API Key</span>
          <input bind:value={apiKey} type="password" placeholder="保存在宿主密钥区" />
        </label>
        <label>
          <span>剪贴板</span>
          <select bind:value={clipboardPolicy}>
            <option value={true}>允许读写</option>
            <option value={false}>仅手动复制</option>
          </select>
        </label>
      </div>
    </section>
  {:else}
    <section class="plugins-view" aria-label="Plugin management">
      <div class="panel-heading">
        <p>插件</p>
        <h1>保持 Core 轻，能力挂在外面</h1>
      </div>

      <div class="plugin-list">
        {#each plugins as plugin}
          <article class="plugin-row">
            <div>
              <strong>{plugin.name}</strong>
              <span>{plugin.kind}</span>
            </div>
            <p>{plugin.permissions.length ? plugin.permissions.join(" / ") : "无额外权限"}</p>
            <label class="switch">
              <input type="checkbox" checked={plugin.enabled} />
              <span></span>
            </label>
          </article>
        {/each}
      </div>
    </section>
  {/if}
</main>
