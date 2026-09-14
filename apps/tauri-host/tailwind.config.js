/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{svelte,ts}"],
  darkMode: ["class"],
  corePlugins: {
    preflight: false
  },
  theme: {
    extend: {
      colors: {
        background: "hsl(var(--background))",
        foreground: "hsl(var(--foreground))",
        border: "hsl(var(--border))",
        input: "hsl(var(--input))",
        ring: "hsl(var(--ring))",
        card: {
          DEFAULT: "hsl(var(--card))",
          foreground: "hsl(var(--card-foreground))"
        },
        popover: {
          DEFAULT: "hsl(var(--popover))",
          foreground: "hsl(var(--popover-foreground))"
        },
        primary: {
          DEFAULT: "hsl(var(--primary))",
          foreground: "hsl(var(--primary-foreground))"
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary))",
          foreground: "hsl(var(--secondary-foreground))"
        },
        muted: {
          DEFAULT: "hsl(var(--muted))",
          foreground: "hsl(var(--muted-foreground))"
        },
        accent: {
          DEFAULT: "hsl(var(--accent))",
          foreground: "hsl(var(--accent-foreground))"
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive))",
          foreground: "hsl(var(--destructive-foreground))"
        },
        blue: {
          400: "#409CFF",
          500: "#0A84FF",
          600: "#0060DF"
        },
        // CC Switch 把 zinc 灰阶命名为 gray 使用（hover:bg-gray-100、
        // text-gray-500、dark:hover:bg-gray-800 等配方依赖这组值）
        gray: {
          50: "#fafafa",
          100: "#f4f4f5",
          200: "#e4e4e7",
          300: "#d4d4d8",
          400: "#a1a1aa",
          500: "#71717a",
          600: "#636366",
          700: "#48484A",
          800: "#3A3A3C",
          900: "#2C2C2E",
          950: "#1C1C1E"
        }
      },
      // 字号与行高钉死为项目刻度：meta 12/18、body 14/21、title 18/27，
      // 与 :root 的 --font-meta/--font-body/--font-title 完全一致
      fontSize: {
        xs: ["12px", "18px"],
        sm: ["14px", "21px"],
        base: ["14px", "21px"],
        lg: ["18px", "27px"],
        xl: ["20px", "30px"]
      },
      // 圆角改用 px，避免 rem 换算出 5.25px 这类半像素
      // 与 CC Switch 的 tailwind.config 一致
      animation: {
        "fade-in": "fadeIn 0.5s ease-out",
        "slide-up": "slideUp 0.5s ease-out",
        "slide-down": "slideDown 0.3s ease-out",
        "slide-in-right": "slideInRight 0.3s ease-out",
        "accordion-down": "accordion-down 0.2s ease-out",
        "accordion-up": "accordion-up 0.2s ease-out"
      },
      keyframes: {
        fadeIn: { "0%": { opacity: "0" }, "100%": { opacity: "1" } },
        slideUp: {
          "0%": { transform: "translateY(20px)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" }
        },
        slideDown: {
          "0%": { transform: "translateY(-100%)", opacity: "0" },
          "100%": { transform: "translateY(0)", opacity: "1" }
        },
        slideInRight: {
          "0%": { transform: "translateX(100%)", opacity: "0" },
          "100%": { transform: "translateX(0)", opacity: "1" }
        },
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--bits-accordion-content-height)" }
        },
        "accordion-up": {
          from: { height: "var(--bits-accordion-content-height)" },
          to: { height: "0" }
        }
      },
      borderRadius: {
        // 与 CC Switch 的 tailwind.config 一致
        sm: "6px",
        md: "8px",
        lg: "12px",
        xl: "14px",
        "2xl": "16px"
      },
      fontFamily: {
        sans: [
          "Segoe UI Variable",
          "SF Pro Display",
          "Microsoft YaHei UI",
          "Segoe UI",
          "system-ui",
          "sans-serif"
        ],
        // CC Switch 的 mono 栈：结果输出、代码与 JSON 场景使用
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "SF Mono",
          "Consolas",
          "Liberation Mono",
          "Menlo",
          "monospace"
        ]
      }
    }
  },
  plugins: [require("tailwindcss-animate")]
};
