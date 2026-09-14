import { existsSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  DemoCoreBridge,
  TauriRuntimeBridge,
  createDefaultCoreBridge,
  type CoreBridge,
  type TauriHostApi
} from "./coreBridge";
import {
  createTauriHostApi,
  createTauriHostApiFromModules
} from "./tauriHostApi";
import { createTauriHostStub } from "./testHost";

const frontendRoot = fileURLToPath(new URL("../../", import.meta.url));
const sourceRoot = join(frontendRoot, "src");
const productionExtensions = new Set([".cjs", ".js", ".mjs", ".svelte", ".ts"]);

type SourceFile = {
  path: string;
  source: string;
};

type PackageManifest = {
  dependencies?: Record<string, string>;
  devDependencies?: Record<string, string>;
  optionalDependencies?: Record<string, string>;
};

function collectProductionSourceFiles(root: string): SourceFile[] {
  const files: SourceFile[] = [];

  for (const entry of readdirSync(root, { withFileTypes: true })) {
    const absolutePath = join(root, entry.name);
    if (entry.isDirectory()) {
      files.push(...collectProductionSourceFiles(absolutePath));
      continue;
    }
    if (!entry.isFile() || /\.(?:test|spec)\.[^.]+$/i.test(entry.name)) continue;

    const extension = entry.name.slice(entry.name.lastIndexOf("."));
    if (!productionExtensions.has(extension)) continue;
    files.push({
      path: relative(frontendRoot, absolutePath).replaceAll("\\", "/"),
      source: readFileSync(absolutePath, "utf8")
    });
  }

  return files;
}

function collectModuleSpecifiers(source: string): string[] {
  const specifiers: string[] = [];
  const patterns = [
    /\bfrom\s+["']([^"']+)["']/g,
    /\bimport\s+["']([^"']+)["']/g,
    /\b(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)/g
  ];

  for (const pattern of patterns) {
    for (const match of source.matchAll(pattern)) {
      specifiers.push(match[1]);
    }
  }
  return specifiers;
}

function isForbiddenPackage(specifier: string): boolean {
  const normalized = specifier.toLowerCase();
  return (
    normalized === "next" ||
    normalized.startsWith("next/") ||
    normalized === "prisma" ||
    normalized === "@prisma/client" ||
    normalized.startsWith("@prisma/") ||
    normalized === "z-ai-web-dev-sdk" ||
    normalized.includes("memory-store")
  );
}

describe("production frontend architecture", () => {
  const productionFiles = collectProductionSourceFiles(sourceRoot);

  it("keeps Next API, Prisma, ZAI SDK and browser API backends out of production source", () => {
    const forbiddenRouteRoots = [
      join(frontendRoot, "app", "api"),
      join(frontendRoot, "pages", "api"),
      join(sourceRoot, "app", "api"),
      join(sourceRoot, "pages", "api")
    ];
    expect(forbiddenRouteRoots.filter(existsSync)).toEqual([]);

    const violations = productionFiles.flatMap(({ path, source }) => {
      const findings: string[] = [];
      const forbiddenImports = collectModuleSpecifiers(source).filter(isForbiddenPackage);
      if (forbiddenImports.length > 0) {
        findings.push(`${path}: forbidden imports ${forbiddenImports.join(", ")}`);
      }
      if (/\bfetch\s*\(\s*["'`]\s*\/api(?:\/|["'`])/i.test(source)) {
        findings.push(`${path}: browser fetch targets /api`);
      }
      if (/(?:^|\/)memory-store(?:\.[^/]+)?$/i.test(path)) {
        findings.push(`${path}: memory-store production module`);
      }
      if (/(?:^|\/)app\/api(?:\/|$)|(?:^|\/)pages\/api(?:\/|$)/i.test(path)) {
        findings.push(`${path}: Next API route`);
      }
      return findings;
    });

    expect(violations).toEqual([]);
  });

  it("keeps forbidden backend dependencies out of the frontend manifest", () => {
    const manifest = JSON.parse(
      readFileSync(join(frontendRoot, "package.json"), "utf8")
    ) as PackageManifest;
    const dependencies = {
      ...manifest.dependencies,
      ...manifest.devDependencies,
      ...manifest.optionalDependencies
    };

    expect(Object.keys(dependencies).filter(isForbiddenPackage)).toEqual([]);
    expect(manifest.dependencies?.["@tauri-apps/api"]).toBeTruthy();
  });

  it("keeps the host composition slim with flow controllers outside components", () => {
    const appSource = readFileSync(join(sourceRoot, "App.svelte"), "utf8");
    const lineCount = appSource.split("\n").length;
    expect(lineCount).toBeLessThanOrEqual(1750);

    const flowModules = [
      "appShortcuts",
      "batchFlow",
      "clipboardFlow",
      "cloudPrivacyFlow",
      "diagnosticFlow",
      "downloads",
      "feedbackFlow",
      "firstRunFlow",
      "markdownPreviewFlow",
      "optimizationFlow",
      "semanticModelFlow",
      "settingsFlow",
      "templateFlow",
      "toastState",
      "translationFlow",
      "viewScaleStore",
      "windowControls",
      "workbenchScroll",
      "workbenchView"
    ];
    for (const flowModule of flowModules) {
      const source = readFileSync(join(sourceRoot, "domain", `${flowModule}.ts`), "utf8");
      const svelteImports = collectModuleSpecifiers(source).filter((specifier) =>
        specifier.endsWith(".svelte")
      );
      expect(svelteImports).toEqual([]);
    }
  });

  it("keeps the executable Tauri host and CoreBridge contract wired into App", () => {
    const host: TauriHostApi = createTauriHostStub({
      invoke: async () => undefined,
      listen: async () => () => undefined
    });
    const bridges: CoreBridge[] = [
      new DemoCoreBridge(),
      new TauriRuntimeBridge(host, { requestIdFactory: () => "architecture-test" })
    ];

    expect(typeof createTauriHostApi).toBe("function");
    expect(typeof createTauriHostApiFromModules).toBe("function");
    expect(typeof createDefaultCoreBridge).toBe("function");
    expect(bridges.every((bridge) => typeof bridge.optimize === "function")).toBe(true);

    const appSource = readFileSync(join(sourceRoot, "App.svelte"), "utf8");
    expect(appSource).toMatch(/from\s+["']\.\/domain\/coreBridge["']/);
    expect(appSource).toMatch(/from\s+["']\.\/domain\/tauriHostApi["']/);
    expect(appSource).toContain("createDefaultCoreBridge(");
    expect(appSource).toContain("createTauriHostApi(");
    expect(appSource).not.toContain("new DemoCoreBridge()");
    const feedbackFlowSource = readFileSync(
      join(sourceRoot, "domain", "feedbackFlow.ts"),
      "utf8"
    );
    expect(feedbackFlowSource).toContain(
      "const promptPersisted = await persistPrompt(decision.state);"
    );
    expect(feedbackFlowSource).toMatch(/decision\.shouldPrompt\s*&&\s*promptPersisted/);
    expect(feedbackFlowSource).toContain("createPromptFeedbackPayload({");
    expect(appSource).toContain("const promptAvailable =");
    expect(appSource).toContain("await feedbackFlow.recordCompletion(promptAvailable);");
    expect(appSource).not.toContain('openFeedback(sentiment, "prompt", false)');
    const mainStart = appSource.indexOf("<main");
    const windowStart = /<section\s+class="window"/.exec(appSource)?.index ?? -1;
    expect(mainStart).toBeGreaterThanOrEqual(0);
    expect(windowStart).toBeGreaterThan(mainStart);
    expect(appSource.slice(mainStart, windowStart)).toContain("data-dialog-focus-fallback");
    expect(appSource.slice(windowStart, windowStart + 220)).not.toContain(
      "data-dialog-focus-fallback"
    );

    const settingsSource = readFileSync(
      join(sourceRoot, "components", "settings", "SettingsDialog.svelte"),
      "utf8"
    );
    expect(settingsSource).not.toContain("手动固定");
    expect(settingsSource).toContain('releaseStatus === "experimental"');
    expect(settingsSource).toContain('!element.closest("[inert]")');

    const firstRunSource = readFileSync(
      join(sourceRoot, "components", "onboarding", "FirstRunDialog.svelte"),
      "utf8"
    );
    expect(firstRunSource).toContain('!element.closest("[inert]")');

    const promptSource = readFileSync(
      join(sourceRoot, "components", "feedback", "FeedbackPromptDialog.svelte"),
      "utf8"
    );
    expect(promptSource).toContain('role="region"');
    expect(promptSource).not.toContain('aria-modal="true"');
    expect(promptSource).toContain('translate("这次结果有帮助吗？")');

    const scenePromptSource = readFileSync(
      join(sourceRoot, "components", "workbench", "ScenePromptDialog.svelte"),
      "utf8"
    );
    expect(scenePromptSource).toContain('translate("当前场景：{scene}"');

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    // CC Switch toggle-row：bg-card/50 卡片 + 图标座 + 底边线分节头
    expect(styles).toContain(".settings-content .settings-toggle .settings-toggle-icon");
    expect(styles).toContain(".settings-content .settings-toggle .settings-toggle-text");
    expect(styles).toMatch(/\.settings-toggle \{[^}]*hsl\(var\(--card\) \/ 0\.5\)/);
    expect(styles).toMatch(/\.settings-content h3 \{[^}]*border-bottom: 1px solid hsl\(var\(--border\) \/ 0\.4\)/);

    const tauriAdapterSource = readFileSync(
      join(dirname(fileURLToPath(import.meta.url)), "tauriHostApi.ts"),
      "utf8"
    );
    expect(collectModuleSpecifiers(tauriAdapterSource)).toEqual(
      expect.arrayContaining(["@tauri-apps/api/core", "@tauri-apps/api/event"])
    );
  });

  it("wires the redesigned shell and workbench to existing host actions", () => {
    const appSource = readFileSync(join(sourceRoot, "App.svelte"), "utf8");
    for (const component of [
      "AppToolbar",
      "StatusBar",
      "SettingsDialog",
      "TranslationDialog",
      "MarkdownPreviewDialog",
      "TemplateManagerDialog",
      "BatchDialog",
      "CommandPalette",
      "ConfirmDialog",
      "ClipboardConfirmDialog",
      "ResultCompareDialog",
      "PluginDialog",
      "FirstRunDialog",
      "Toast",
      "InputPane",
      "ConfigSummary",
      "ResultPane",
      "AdjustPanel",
      "ScenePromptDialog"
    ]) {
      expect(appSource).toMatch(new RegExp(`import\\s+${component}\\s+from`));
      expect(appSource).toContain(`<${component}`);
    }

    for (const hostAction of [
      "runOptimization",
      "cancelRun",
      "readClipboard",
      "copyResult",
      "askReplaceClipboard",
      "openHistoryView",
      "rateCurrentResult",
      "hide_main_window"
    ]) {
      expect(appSource).toContain(hostAction);
    }

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(styles).toContain(".workbench-grid");
    // 调整面板已重建为 DialogShell 弹窗（与 CC Switch 同构），不再有专属外壳样式
    const adjustSource = readFileSync(
      join(sourceRoot, "components", "workbench", "AdjustPanel.svelte"),
      "utf8"
    );
    expect(adjustSource).toContain('from "@/components/ui/DialogShell.svelte"');
    expect(adjustSource).toContain('from "@/components/ui/SegmentedControl.svelte"');
    expect(adjustSource).toContain('from "@/components/ui/AppSelect.svelte"');
    expect(styles).not.toContain(".adjust-dialog");
    expect(styles).toMatch(/\.confirm-layer\s*\{[\s\S]*z-index:\s*80/);
    expect(styles).toMatch(/@media\s*\(max-width:\s*620px\)/);
    expect(appSource).not.toContain("false &&");
    expect(appSource).not.toContain("closeMoreActions");
    expect(appSource).not.toContain("window.confirm");
    expect(appSource).not.toMatch(/class=["'](?:command|template|batch)-dialog["']/);
  });

  it("keeps the workbench focused on one primary action", () => {
    const inputSource = readFileSync(
      join(sourceRoot, "components", "workbench", "InputPane.svelte"),
      "utf8"
    );
    const configSource = readFileSync(
      join(sourceRoot, "components", "workbench", "ConfigSummary.svelte"),
      "utf8"
    );
    expect(inputSource).not.toContain('<span>{translate("常用任务")}</span>');
    expect(inputSource).not.toContain('<small>{translate(action.hint)}</small>');
    expect(configSource).toContain('<details class="advanced-config">');
    expect(configSource).toContain('translate("更多设置")');
  });

  it("uses a native full-bleed shell window (CC Switch parity)", () => {
    const tauriConfig = JSON.parse(
      readFileSync(join(frontendRoot, "src-tauri", "tauri.conf.json"), "utf8")
    ) as {
      app: {
        windows: Array<{
          width?: number;
          height?: number;
          minWidth?: number;
          minHeight?: number;
          transparent?: boolean;
          decorations?: boolean;
          resizable?: boolean;
        }>;
      };
    };
    const window = tauriConfig.app.windows[0] ?? {};
    expect(window.transparent).not.toBe(true);
    expect(window.decorations).toBe(true);
    expect(window.resizable).toBe(true);
    expect(window.width).toBe(1200);
    expect(window.height).toBe(650);
    expect(window.minWidth).toBe(945);
    expect(window.minHeight).toBe(600);

    const appSource = readFileSync(join(sourceRoot, "App.svelte"), "utf8");
    expect(appSource).not.toMatch(/import\s+ReflexTitleBar\s+from/);

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    // 壳层三段：64px 顶栏 / 弹性正文 / 32px 状态条（对齐 CC Switch 的 64px header）
    expect(styles).toMatch(/\.app-shell \.window \{[^}]*grid-template-rows: 64px minmax\(0, 1fr\) 32px;/s);
  });

  it("keeps one focus contract (CC Switch parity)", () => {
    const appCss = readFileSync(join(sourceRoot, "app.css"), "utf8");
    // 全局只有一条焦点规则：2px 蓝色 outline + 2px 偏移，无光晕
    expect(appCss).toMatch(/\*:focus-visible \{\s*outline: 2px solid #0a84ff;\s*outline-offset: 2px;\s*\}/);

    // 组件不得再出现「3px 环 + 边框变色」的旧版 registry 配方（叠三层会成双蓝圈）
    const offenders: string[] = [];
    for (const { path, source } of productionFiles) {
      if (!path.endsWith(".svelte")) continue;
      for (const token of [
        "focus-visible:ring-[3px]",
        "focus-visible:border-ring",
        "focus-visible:ring-ring/50"
      ]) {
        if (source.includes(token)) offenders.push(`${path}:${token}`);
      }
    }
    expect(offenders).toEqual([]);

    // styles.css 里不允许再出现逐组件的 focus-visible 描边/光晕覆盖；
    // 只做抑制（outline: none / transparent）是允许的，那正是控件把焦点交给 ring 的方式
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    const focusBlocks = [...styles.matchAll(/:focus-visible[^{]*\{([^}]*)\}/g)].map((m) => m[1]);
    const decorated = focusBlocks
      .map((body) => body.replace(/outline(-[a-z]+)?:\s*(none|transparent)\s*;?/g, ""))
      .filter((body) => /outline|box-shadow|border-color/.test(body));
    expect(decorated).toEqual([]);
  });

  it("keeps one spacing and surface contract (CC Switch parity)", () => {
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    const layer = styles.slice(styles.indexOf("最终间距与表面契约"));

    // 间距尺度：页面 gutter 24px、面板间距 16px、底部呼吸 24px
    expect(layer).toMatch(/\.app-shell\.outer-contour \.app-toolbar \{[^}]*padding: 0 24px;/s);
    expect(layer).toMatch(/\.app-shell\.outer-contour \.status-bar \{[^}]*padding: 0 24px;/s);
    expect(styles).toMatch(/\.app-shell\.outer-contour \.workbench-grid \{\s*gap: 16px;/);
    expect(styles).toMatch(/\.app-shell\.outer-contour \.workbench-surface \{\s*padding: 16px 24px 24px;/);

    // 表面层次：卡片 = 页面底色令牌 + 描边 + xl 圆角（14，嵌套内层 12），静止无阴影
    expect(styles).toMatch(/\.app-shell\.outer-contour \.workbench-grid > \.result-pane \{[^}]*background: hsl\(var\(--background\)\);[^}]*border: 1px solid var\(--line\);[^}]*border-radius: var\(--radius-xl\);[^}]*box-shadow: none;/s);

    // 圆角刻度对齐 CC Switch：md 8 / lg 12 / xl 14
    expect(styles).toMatch(/--radius-sm: 6px;\s*--radius-md: 8px;\s*--radius-lg: 12px;\s*--radius-xl: 14px;/);

    // 圆角不再出现历史遗留的碎片取值
    const radii = [...styles.matchAll(/border-radius\s*:\s*([^;}\n]+)/g)].map((m) => m[1].trim());
    const allowed = new Set([
      "0",
      "4px",
      "6px",
      "8px",
      "12px",
      "14px",
      "50%",
      "999px",
      "var(--radius)",
      "var(--radius-md)",
      "var(--radius-lg)",
      "var(--radius-xl)",
      "calc(var(--radius) + 4px)"
    ]);
    expect(radii.filter((value) => !value.startsWith("0 ") && !allowed.has(value))).toEqual([]);
  });

  it("keeps the first-success loop in the host UI without leaking credentials", () => {
    const appSource = readFileSync(join(sourceRoot, "App.svelte"), "utf8");
    const inputSource = readFileSync(
      join(sourceRoot, "components", "workbench", "InputPane.svelte"),
      "utf8"
    );
    const resultSource = readFileSync(
      join(sourceRoot, "components", "workbench", "ResultPane.svelte"),
      "utf8"
    );
    const firstRunSource = readFileSync(
      join(sourceRoot, "components", "onboarding", "FirstRunDialog.svelte"),
      "utf8"
    );
    const settingsSource = readFileSync(
      join(sourceRoot, "components", "settings", "SettingsDialog.svelte"),
      "utf8"
    );

    const firstRunFlowSource = readFileSync(
      join(sourceRoot, "domain", "firstRunFlow.ts"),
      "utf8"
    );
    const optimizationFlowSource = readFileSync(
      join(sourceRoot, "domain", "optimizationFlow.ts"),
      "utf8"
    );

    expect(firstRunFlowSource).toContain("first_run_activation");
    expect(appSource).toContain("availableActivationRoutes($cloudAvailability)");
    expect(appSource).toContain("completeFirstRunActivation()");
    expect(appSource).toContain('inert={state.overlay === "settings" || $activationOpen}');
    expect(optimizationFlowSource).toContain("runtime_stream_failed");
    expect(optimizationFlowSource).toMatch(
      /try\s*\{[\s\S]{0,200}for await \(const event of deps\.coreBridge\(\)\.optimize[\s\S]{0,1600}\}\s*catch[\s\S]{0,600}\}\s*finally/
    );
    const postponeFirstRunBody = appSource.match(
      /function postponeFirstRun\(\)\s*\{([\s\S]*?)\n {2}\}/
    )?.[1] ?? "";
    expect(postponeFirstRunBody).toContain("firstRunFlow.postpone()");
    expect(postponeFirstRunBody).not.toContain("completeActivation");
    expect(postponeFirstRunBody).not.toContain("persistActivationState");
    expect(appSource).toMatch(
      /async function finishFirstRunFromSettings\(providerId: string \| null\)[\s\S]{0,280}completeFirstRunActivation\(\)[\s\S]{0,180}cancelSettingsView\(\)/
    );
    expect(appSource).toMatch(
      /<\/section>[\s\S]{0,8000}\{#if \$activationOpen && state\.overlay !== "settings"\}[\s\S]{0,480}<FirstRunDialog/
    );
    expect(appSource).toMatch(
      /\{#if activeView === "history"\}[\s\S]{0,200}<HistoryView \/>[\s\S]{0,200}\{:else if activeView !== "settings"\}[\s\S]{0,8000}\{:else\}\s*<SettingsDialog\s+variant="page"/
    );
    expect(firstRunSource).toContain("focusableSelector");
    expect(firstRunSource).toContain("onClose={() => void onLater()}");
    expect(firstRunSource).toContain('data-dialog-focus-fallback');
    expect(settingsSource).toContain("focusableSelector");
    expect(settingsSource).toContain("autofocusClose={false}");
    expect(settingsSource).toContain('data-dialog-focus-fallback');
    const dialogShellSource = readFileSync(
      join(sourceRoot, "components", "ui", "DialogShell.svelte"),
      "utf8"
    );
    expect(dialogShellSource).toContain("Escape");
    expect(dialogShellSource).toContain("trapFocus");
    expect(appSource).toContain("data-dialog-focus-fallback");
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(styles).toMatch(
      /\.app-shell \.settings-layer\s*\{[^}]*position:\s*fixed;[^}]*inset:\s*0;/s
    );
    expect(appSource).toContain("quickActions={quickActions}");
    expect(appSource).toContain("trustSummary={generationTrust}");
    expect(inputSource).toContain("onQuickAction");
    expect(resultSource).toContain('translate("复制结果")');
    expect(resultSource).toContain('translate("对比原文")');
    expect(resultSource).toContain('translate("再调整")');
    expect(resultSource).toContain('translate("更多结果工具")');
    expect(appSource).not.toMatch(/first_run_activation[\s\S]{0,240}(?:api[_-]?key|secret|token|endpoint)/i);
  });

  it("keeps the history view componentized and responsive", () => {
    const historySource = readFileSync(
      join(sourceRoot, "components", "history", "HistoryView.svelte"),
      "utf8"
    );
    for (const component of ["HistoryFilters", "HistoryList", "HistoryDetail"]) {
      expect(historySource).toMatch(new RegExp(`import\\s+${component}\\s+from`));
      expect(historySource).toContain(`<${component}`);
    }
    // 历史记录是主窗口内的视图（与 CC Switch 同构），不再独立开窗
    expect(existsSync(join(sourceRoot, "HistoryApp.svelte"))).toBe(false);
    const shellSource = readFileSync(join(sourceRoot, "App.svelte"), "utf8");
    expect(shellSource).toContain('import HistoryView from "./components/history/HistoryView.svelte"');
    expect(shellSource).toContain('activeView === "history"');

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(styles).not.toMatch(/\.history-shell\s*\{[^}]*min-width:\s*760px/s);
    expect(styles).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*\.history-workspace/);
    expect(historySource).toContain("if (!config.history_enabled)");
    expect(historySource).toMatch(/event\.status === "error" \|\| event\.status === "cancelled"/);
  });

  it("keeps shared UI primitives as the single source for common materials", () => {
    for (const component of ["DialogShell", "EmptyState", "Spinner", "AppSelect", "SegmentedControl"]) {
      expect(existsSync(join(sourceRoot, "components", "ui", `${component}.svelte`))).toBe(true);
    }
    // shadcn Button 是唯一按钮原语：手写壳层已退役
    expect(existsSync(join(sourceRoot, "components", "ui", "BaseButton.svelte"))).toBe(false);
    expect(readFileSync(join(sourceRoot, "styles.css"), "utf8")).not.toContain(".ui-button");

    const historyList = readFileSync(join(sourceRoot, "components", "history", "HistoryList.svelte"), "utf8");
    const historyDetail = readFileSync(join(sourceRoot, "components", "history", "HistoryDetail.svelte"), "utf8");
    expect(historyList).toContain('from "../ui/EmptyState.svelte"');
    expect(historyDetail).toContain('from "../ui/EmptyState.svelte"');
  });

  it("routes every action button through the shared shadcn Button", () => {
    const legacyActionButton = productionFiles
      .filter(({ path }) => path.endsWith(".svelte") && !path.includes("components/ui/"))
      .filter(({ source }) =>
        [...source.matchAll(/<button[^>]*class="([^"]*)"/g)].some((match) =>
          match[1].split(/\s+/).some((token) => ["outline", "primary", "danger-icon"].includes(token))
        )
      )
      .map(({ path }) => path);
    expect(legacyActionButton).toEqual([]);

    const sharedButtonUsers = productionFiles
      .filter(({ path }) => path.endsWith(".svelte") && !path.includes("components/ui/"))
      .filter(({ source }) => /<Button[\s>]/.test(source));
    expect(sharedButtonUsers.length).toBeGreaterThanOrEqual(12);

    const toolbar = readFileSync(
      join(sourceRoot, "components", "shell", "AppToolbar.svelte"),
      "utf8"
    );
    expect(toolbar).toContain('from "@/components/ui/button"');
    expect(toolbar).toContain("toolbar-shortcuts");

    const maintenanceMenu = readFileSync(
      join(sourceRoot, "components", "history", "HistoryMaintenanceMenu.svelte"),
      "utf8"
    );
    expect(maintenanceMenu).toContain('from "@/components/ui/button"');
    expect(maintenanceMenu).toContain("history-menu");
  });

  it("routes every select through the shared shadcn-based AppSelect wrapper", () => {
    const nativeSelectUsages = productionFiles
      .filter(({ path }) => path.endsWith(".svelte"))
      .filter(({ source }) => /<(?:select|option)[\s>]/.test(source))
      .map(({ path }) => path);
    expect(nativeSelectUsages).toEqual([]);

    const selectSource = readFileSync(
      join(sourceRoot, "components", "ui", "AppSelect.svelte"),
      "utf8"
    );
    expect(selectSource).toContain('from "@/components/ui/select"');
    expect(selectSource).toContain("<Select.Trigger");
    expect(selectSource).toContain("<Select.Content");
    expect(selectSource).toContain("<Select.Item");
    expect(selectSource).toContain("aria-label={ariaLabel}");

    const rawSelectUsages = productionFiles
      .filter(({ path }) => path.endsWith(".svelte") && !path.includes("components/ui/"))
      .filter(({ source }) => /<Select\.(Root|Trigger|Content|Item)/.test(source))
      .map(({ path }) => path);
    expect(rawSelectUsages).toEqual([]);
  });

  it("uses the token-only type and leading scale everywhere", () => {
    const styles = [
      {
        path: "src/styles.css",
        source: readFileSync(join(sourceRoot, "styles.css"), "utf8")
      },
      ...productionFiles.filter(({ path }) => path.endsWith(".svelte"))
    ];
    const allowed = new Set([
      "var(--font-meta)",
      "var(--font-body)",
      "var(--font-title)",
      // 徽章级：只用于内联标签胶囊，不参与正文层级
      "var(--font-badge)",
      // 根字号的 rem 基准，只允许出现在 styles.css 的 :root 上
      "16px"
    ]);
    const allowedLeading = new Set([
      "var(--leading-none)",
      "var(--leading-meta)",
      "var(--leading-body)",
      "var(--leading-prose)",
      "var(--leading-title)",
      "var(--leading-badge)"
    ]);
    const declarations = styles.flatMap(({ path, source }) =>
      [...source.matchAll(/font-size\s*:\s*([^;}\n]+)/g)].map((match) => ({
        path,
        value: match[1].replace(/\s*!important\s*$/, "").trim()
      }))
    );
    const leading = styles.flatMap(({ path, source }) =>
      [...source.matchAll(/line-height\s*:\s*([^;}\n]+)/g)].map((match) => ({
        path,
        value: match[1].replace(/\s*!important\s*$/, "").trim()
      }))
    );

    expect(styles[0].source).toContain("--font-meta: 12px");
    expect(styles[0].source).toContain("--font-body: 14px");
    expect(styles[0].source).toContain("--font-title: 18px");
    expect(styles[0].source).toContain("--font-badge: 10px");
    expect(styles[0].source).toContain("--leading-none: 1");
    expect(styles[0].source).toContain("--leading-meta: 18px");
    expect(styles[0].source).toContain("--leading-body: 21px");
    expect(styles[0].source).toContain("--leading-prose: 23px");
    expect(styles[0].source).toContain("--leading-title: 27px");
    expect(styles[0].source).toContain("--leading-badge: 14px");
    expect(styles[0].source).not.toMatch(
      /(?:\.settings-head h2|\.settings-content h3)[^{]*\{[^}]*font-size:\s*var\(--font-title\)/s
    );
    expect(declarations.filter(({ value }) => !allowed.has(value))).toEqual([]);
    expect(declarations.filter(({ value }) => value === "16px")).toEqual([
      { path: "src/styles.css", value: "16px" }
    ]);
    // 倍数列高会按各自字号重算出 16.2 / 17.76 / 19.8 这类碎片值，只允许 token。
    expect(leading.filter(({ value }) => !allowedLeading.has(value))).toEqual([]);
    expect(styles[0].source).toMatch(/:root\s*\{[^}]*font-size:\s*16px/s);
  });

  it("keeps one empty-state recipe across workbench and history (CC Switch parity)", () => {
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");

    // 唯一配方：36/40 留白、18px 标题、14px 说明、512px 行宽、虚线卡片
    expect(styles).toMatch(
      /\.app-shell\.outer-contour \.result-pane \.center-state \{\s*gap: 16px;\s*padding: 40px;/s
    );
    expect(styles).toMatch(
      /\.app-shell\.outer-contour \.result-pane \.center-state h3 \{[^}]*font-size: var\(--font-title\);[^}]*font-weight: 600;[^}]*line-height: var\(--leading-title\);/s
    );
    expect(styles).toMatch(
      /\.app-shell\.outer-contour \.result-pane \.center-state p \{[^}]*max-width: 512px;[^}]*font-size: var\(--font-body\);[^}]*line-height: var\(--leading-body\);/s
    );
    expect(styles).toMatch(
      /\.app-shell\.outer-contour \.result-pane \.center-state\.empty-state \{[^}]*border: 1px dashed var\(--line\);[^}]*border-radius: var\(--radius-lg\);/s
    );

    // 历史上 result-pane 有 4 代 .center-state 规则互相覆盖，任何一代回归都会重新分裂空状态
    const legacyGenerations = [...styles.matchAll(/^\.app-shell \.result-pane \.center-state[^\n]*\{/gm)];
    expect(legacyGenerations).toEqual([]);

    // 组件不得再自带一套空状态排版
    const competingTypography = productionFiles
      .filter(({ path }) => path.endsWith(".svelte"))
      .filter(({ source }) => /\.center-state (?:h3|p)[^{]*\{[^}]*font-size/s.test(source))
      .map(({ path }) => path);
    expect(competingTypography).toEqual([]);
  });

  it("never falls back to the browser's native disclosure marker", () => {
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    const componentStyles = productionFiles
      .filter(({ path }) => path.endsWith(".svelte"))
      .map(({ path, source }) => ({ path, source: source.match(/<style[^>]*>([\s\S]*)<\/style>/)?.[1] ?? "" }))
      .filter(({ source }) => source.length > 0);

    // 用 CSS 三角形冒充 marker 会重新引入与原生 ▶ 一样的实心三角
    const triangleTrick = [...componentStyles, { path: "src/styles.css", source: styles }]
      .filter(({ source }) => /border-top: 4px solid transparent/.test(source))
      .map(({ path }) => path);
    expect(triangleTrick).toEqual([]);

    // 每条 summary 元素规则都要显式关掉原生 marker
    // （::-webkit-details-marker / ::marker 本身就是抑制规则，不在此列；
    //   summary-chip、config-summary 这类把 summary 当子串的类名，
    //   以及 .history-menu summary span 这类后代规则也不算）
    const summaryRules = [...styles.matchAll(/([^{}\n]*)\{([^}]*)\}/gm)]
      .filter(([, selector]) => / summary(?::[a-z-]+(?:\([^)]*\))?)*\s*$/.test(selector));
    expect(summaryRules.length).toBeGreaterThanOrEqual(3);
    const missing = summaryRules
      .filter(([, , body]) => !/list-style:\s*none/.test(body))
      .map(([, selector]) => selector.trim());
    expect(missing).toEqual([]);

    // 展开指示由 lucide 图标承担，打开的 details 旋转 90°
    for (const path of ["ConfigSummary", "ResultPane"]) {
      const component = readFileSync(join(sourceRoot, "components", "workbench", `${path}.svelte`), "utf8");
      expect(component).toContain("@lucide/svelte/icons/chevron-right");
      expect(component).toContain("disclosure-caret");
    }
    expect(styles).toMatch(/\.secondary-tools\[open\] \.disclosure-caret \{\s*transform: rotate\(90deg\);/s);
  });

  it("keeps component styles on the shared spacing and radius scale", () => {
    const spacingScale = new Set([0, 1, 2, 4, 6, 8, 10, 12, 14, 16, 20, 24, 32, 36, 40, 48, 56, 64, 80]);
    const radiusScale = new Set(["0", "4px", "6px", "8px", "12px", "14px", "16px", "50%", "999px", "9999px"]);
    const spacingOffenders: string[] = [];
    const radiusOffenders: string[] = [];

    for (const { path, source } of productionFiles.filter(({ path }) => path.endsWith(".svelte"))) {
      const styleBlock = source.match(/<style[^>]*>([\s\S]*)<\/style>/)?.[1];
      if (!styleBlock) continue;
      styleBlock.split("\n").forEach((line, index) => {
        const trimmed = line.trim();
        if (trimmed.startsWith("/*") || trimmed.startsWith("*")) return;
        const spacing = /^(gap|row-gap|column-gap|padding|padding-\w+|margin|margin-\w+)\s*:\s*(.+?);?$/.exec(trimmed);
        if (spacing) {
          const off = [...spacing[2].matchAll(/(?<![\w-])(\d+(?:\.\d+)?)px/g)]
            .map((match) => Number(match[1]))
            .filter((value) => !spacingScale.has(value));
          if (off.length) spacingOffenders.push(`${path}:${index + 1} ${trimmed}`);
        }
        const radius = /^border-radius\s*:\s*(.+?);?$/.exec(trimmed);
        if (radius) {
          const off = radius[1]
            .split(/\s+/)
            .filter((value) => !value.startsWith("var(") && !radiusScale.has(value));
          if (off.length) radiusOffenders.push(`${path}:${index + 1} ${trimmed}`);
        }
      });
    }

    expect(spacingOffenders).toEqual([]);
    expect(radiusOffenders).toEqual([]);
  });

  it("keeps Tailwind v3-compatible class names in production source", () => {
    // 这些是 Tailwind v4 的类名/语法：在 v3 下不生成任何 CSS，写了等于没写
    const deadTw4Tokens: Array<[RegExp, string]> = [
      [/shadow-xs/, "shadow-xs (v3 应写 shadow-sm)"],
      [/outline-hidden/, "outline-hidden (v3 应写 outline-none)"],
      [/rounded-xs/, "rounded-xs (v3 应写 rounded-sm)"],
      [/field-sizing-content/, "field-sizing-content (v3 无此能力)"],
      [/data-highlighted:/, "data-highlighted: (v3 应写 data-[highlighted]:)"],
      [/\*:\[svg\]:/, "*:[svg]: (v3 不支持任意子选择器变体)"]
    ];
    const offenders: string[] = [];
    for (const { path, source } of productionFiles) {
      for (const [pattern, reason] of deadTw4Tokens) {
        if (pattern.test(source)) offenders.push(`${path}: ${reason}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("keeps raw <button> elements out of business components", () => {
    // shadcn Button 是唯一按钮原语；ui 目录内的原语实现（button/switch 等）不受限。
    // 名单是存量迁移欠账，只许减少不许增加。
    const legacyRawButtonAllowlist = new Set([
      "src/components/onboarding/FirstRunDialog.svelte",
      "src/components/tools/TranslationDialog.svelte",
      "src/components/tools/TemplateManagerDialog.svelte",
      "src/components/tools/BatchDialog.svelte",
      "src/components/tools/MarkdownPreviewDialog.svelte",
      "src/components/history/HistoryList.svelte"
    ]);
    const rawButtonUsers = productionFiles
      .filter(({ path }) => path.endsWith(".svelte") && !path.includes("components/ui/"))
      .filter(({ source }) => /<button[\s>]/.test(source))
      .map(({ path }) => path);
    expect(rawButtonUsers.filter((path) => !legacyRawButtonAllowlist.has(path))).toEqual([]);
  });

  it("keeps the theme system dual-track (explicit choice + OS follow) (CC Switch parity)", () => {
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    // 显式轨道：data-theme=dark 直接命中；跟随轨道：system + prefers-color-scheme
    expect(styles).toContain(':root[data-theme="dark"]');
    expect(styles).toMatch(/@media\s*\(prefers-color-scheme:\s*dark\)\s*\{[\s\S]*\[data-theme="system"\]/);

    const themeApplySource = readFileSync(
      join(sourceRoot, "domain", "themeApply.ts"),
      "utf8"
    );
    expect(themeApplySource).toContain("export function watchSystemTheme");
    expect(themeApplySource).toContain("matchMedia");

    // 主窗口与快捷面板都必须订阅系统主题切换，否则 OS 换肤后 UI 不跟随
    for (const entry of ["App.svelte", "PanelApp.svelte"]) {
      const source = readFileSync(join(sourceRoot, entry), "utf8");
      expect(source).toContain("watchSystemTheme(");
    }
  });
});
