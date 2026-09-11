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
    expect(appSource).toContain(
      "const promptPersisted = await persistFeedbackPrompt(decision.state);"
    );
    expect(appSource).toMatch(/decision\.shouldPrompt\s*&&\s*promptPersisted/);
    expect(appSource).toContain("const promptAvailable =");
    expect(appSource).toContain("createPromptFeedbackPayload({");
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
    expect(styles).toContain(".settings-content label.settings-toggle > span");

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
      "ReflexTitleBar",
      "NavRail",
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
      "openHistoryWindow",
      "rateCurrentResult",
      "hide_main_window"
    ]) {
      expect(appSource).toContain(hostAction);
    }

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(styles).toContain(".workbench-grid");
    expect(styles).toContain(".adjust-dialog");
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
    const titleBarSource = readFileSync(
      join(sourceRoot, "components", "shell", "ReflexTitleBar.svelte"),
      "utf8"
    );

    expect(inputSource).not.toContain('<span>{translate("常用任务")}</span>');
    expect(inputSource).not.toContain('<small>{translate(action.hint)}</small>');
    expect(configSource).toContain('<details class="advanced-config">');
    expect(configSource).toContain('translate("更多设置")');
    expect(titleBarSource).toContain('<details class="workspace-controls">');
  });

  it("uses one exposed outer window contour instead of nested workbench cards", () => {
    const tauriConfig = JSON.parse(
      readFileSync(join(frontendRoot, "src-tauri", "tauri.conf.json"), "utf8")
    ) as { app: { windows: Array<{ transparent?: boolean }> } };
    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");

    expect(tauriConfig.app.windows[0]?.transparent).toBe(true);
    expect(styles).toMatch(
      /\.app-shell\.outer-contour\s*\{[^}]*padding:\s*0;[^}]*background:\s*transparent;[^}]*border-radius:\s*24px;[^}]*overflow:\s*hidden;/s
    );
    expect(styles).toMatch(
      /\.app-shell\.outer-contour \.workbench-grid\s*\{[^}]*gap:\s*0;/s
    );
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

    expect(appSource).toContain("first_run_activation");
    expect(appSource).toContain("availableActivationRoutes($cloudAvailability)");
    expect(appSource).toContain("completeFirstRunActivation()");
    expect(appSource).toContain('inert={state.overlay === "settings" || activationOpen}');
    expect(appSource).toContain("runtime_stream_failed");
    expect(appSource).toMatch(
      /try\s*\{[\s\S]{0,200}for await \(const event of coreBridge\.optimize[\s\S]{0,1600}\}\s*catch[\s\S]{0,600}\}\s*finally/
    );
    const postponeFirstRunBody = appSource.match(
      /function postponeFirstRun\(\)\s*\{([\s\S]*?)\n {2}\}/
    )?.[1] ?? "";
    expect(postponeFirstRunBody).toContain("activationOpen = false");
    expect(postponeFirstRunBody).toContain('activationNotice = ""');
    expect(postponeFirstRunBody).not.toContain("completeActivation");
    expect(postponeFirstRunBody).not.toContain("persistActivationState");
    expect(appSource).toMatch(
      /async function finishFirstRunFromSettings\(providerId: string \| null\)[\s\S]{0,280}completeFirstRunActivation\(\)[\s\S]{0,180}cancelSettingsView\(\)/
    );
    expect(appSource).toMatch(
      /<\/section>[\s\S]{0,8000}\{#if activationOpen && state\.overlay !== "settings"\}[\s\S]{0,480}<FirstRunDialog/
    );
    expect(appSource).toMatch(
      /<\/section>[\s\S]{0,1200}\{#if state\.overlay === "settings"\}[\s\S]{0,480}<SettingsDialog/
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

  it("keeps the history window componentized and responsive", () => {
    const historySource = readFileSync(join(sourceRoot, "HistoryApp.svelte"), "utf8");
    for (const component of ["HistoryHeader", "HistoryFilters", "HistoryList", "HistoryDetail"]) {
      expect(historySource).toMatch(new RegExp(`import\\s+${component}\\s+from`));
      expect(historySource).toContain(`<${component}`);
    }

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(styles).not.toMatch(/\.history-shell\s*\{[^}]*min-width:\s*760px/s);
    expect(styles).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*\.history-workspace/);
    expect(historySource).toContain("if (!config.history_enabled)");
    expect(historySource).toMatch(/event\.status === "error" \|\| event\.status === "cancelled"/);
  });

  it("keeps shared UI primitives as the single source for common materials", () => {
    for (const component of ["BaseButton", "GlassPanel", "Field", "DialogShell", "EmptyState", "SelectField"]) {
      expect(existsSync(join(sourceRoot, "components", "ui", `${component}.svelte`))).toBe(true);
    }

    const historyList = readFileSync(join(sourceRoot, "components", "history", "HistoryList.svelte"), "utf8");
    const historyDetail = readFileSync(join(sourceRoot, "components", "history", "HistoryDetail.svelte"), "utf8");
    expect(historyList).toContain('from "../ui/EmptyState.svelte"');
    expect(historyDetail).toContain('from "../ui/EmptyState.svelte"');
  });

  it("uses one accessible custom select instead of browser-native option popups", () => {
    const nativeSelectUsages = productionFiles
      .filter(({ path }) => path.endsWith(".svelte"))
      .filter(({ source }) => /<(?:select|option)\b/i.test(source))
      .map(({ path }) => path);
    expect(nativeSelectUsages).toEqual([]);

    const selectSource = readFileSync(
      join(sourceRoot, "components", "ui", "SelectField.svelte"),
      "utf8"
    );
    expect(selectSource).toContain('role="combobox"');
    expect(selectSource).toContain('role="listbox"');
    expect(selectSource).toContain("ArrowDown");
    expect(selectSource).toContain("aria-selected");
    expect(selectSource).toContain("event.stopPropagation()");
    expect(selectSource).toContain('tabindex="-1"');
    expect(selectSource).toContain("scrollIntoView");
    expect(selectSource).toContain("viewportZoom");
  });

  it("uses the three-level typography token scale everywhere", () => {
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
      "var(--font-title)"
    ]);
    const declarations = styles.flatMap(({ path, source }) =>
      [...source.matchAll(/font-size\s*:\s*([^;}\n]+)/g)].map((match) => ({
        path,
        value: match[1].replace(/\s*!important\s*$/, "").trim()
      }))
    );

    expect(styles[0].source).toContain("--font-meta: 12px");
    expect(styles[0].source).toContain("--font-body: 14px");
    expect(styles[0].source).toContain("--font-title: 18px");
    expect(styles[0].source).not.toMatch(
      /(?:\.settings-head h2|\.settings-content h3)[^{]*\{[^}]*font-size:\s*var\(--font-title\)/s
    );
    expect(declarations.filter(({ value }) => !allowed.has(value))).toEqual([]);
  });
});
