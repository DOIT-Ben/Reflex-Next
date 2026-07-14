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
    const host: TauriHostApi = {
      invoke: async () => undefined,
      listen: async () => () => undefined
    };
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
      "Toast",
      "InputPane",
      "ConfigSummary",
      "ResultPane",
      "AdjustPanel"
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

  it("keeps the history window componentized and responsive", () => {
    const historySource = readFileSync(join(sourceRoot, "HistoryApp.svelte"), "utf8");
    for (const component of ["HistoryHeader", "HistoryFilters", "HistoryList", "HistoryDetail"]) {
      expect(historySource).toMatch(new RegExp(`import\\s+${component}\\s+from`));
      expect(historySource).toContain(`<${component}`);
    }

    const styles = readFileSync(join(sourceRoot, "styles.css"), "utf8");
    expect(styles).not.toMatch(/\.history-shell\s*\{[^}]*min-width:\s*760px/s);
    expect(styles).toMatch(/@media\s*\(max-width:\s*760px\)[\s\S]*\.history-workspace/);
  });
});
