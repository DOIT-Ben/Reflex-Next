import { describe, expect, it } from "vitest";
import viteConfig from "../../vite.config";

describe("development server config", () => {
  it("fails fast instead of moving away from the Tauri dev URL", () => {
    expect(viteConfig).toMatchObject({
      server: {
        strictPort: true
      }
    });
  });
});
