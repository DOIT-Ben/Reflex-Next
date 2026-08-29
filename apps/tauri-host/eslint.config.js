import js from "@eslint/js";
import svelte from "eslint-plugin-svelte";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: ["dist/**", "node_modules/**", "src-tauri/target/**"]
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...svelte.configs["flat/recommended"],
  {
    files: ["src/**/*.{ts,svelte}", "vite.config.ts"],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
        ...globals.vitest,
        __REFLEX_APP_VERSION__: "readonly"
      }
    }
  },
  {
    files: ["src/**/*.svelte"],
    languageOptions: {
      parserOptions: {
        extraFileExtensions: [".svelte"],
        parser: tseslint.parser
      }
    }
  },
  {
    rules: {
      "no-control-regex": "off",
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }
      ],
      "svelte/require-each-key": "off"
    }
  },
  {
    files: ["src/App.svelte"],
    rules: {
      "svelte/no-reactive-functions": "off",
      "svelte/infinite-reactive-loop": "off"
    }
  },
  {
    files: ["src/components/tools/MarkdownPreviewDialog.svelte"],
    rules: {
      "svelte/no-at-html-tags": "off"
    }
  }
);
