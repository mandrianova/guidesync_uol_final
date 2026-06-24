import { createTheme, rem } from "@mantine/core";

export const theme = createTheme({
  primaryColor: "teal",
  defaultRadius: "md",
  fontFamily:
    'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
  headings: {
    fontFamily:
      'Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
    sizes: {
      h1: { fontSize: rem(26), lineHeight: "1.08" },
      h2: { fontSize: rem(24), lineHeight: "1.12" },
      h3: { fontSize: rem(18), lineHeight: "1.2" }
    }
  },
  colors: {
    teal: [
      "#e6f5f2",
      "#cceae5",
      "#99d5ca",
      "#67c0af",
      "#34ab94",
      "#0f766e",
      "#0b5f59",
      "#094b46",
      "#063834",
      "#042522"
    ]
  },
  components: {
    Button: {
      defaultProps: {
        fw: 750
      }
    },
    Paper: {
      defaultProps: {
        radius: "md"
      }
    }
  }
});
