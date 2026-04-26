import type { Metadata } from "next";
import "@assistant-ui/react/styles/index.css";
import "@assistant-ui/react/styles/themes/default.css";
import "../styles/globals.css";
import { ThemeProvider } from "@/lib/theme";

export const metadata: Metadata = {
  title: "OpenFilingRAG — filing-aware research agent",
  description:
    "Dynamic RAG prototype for company-disclosure analysis. Streams agent reasoning, retrieved evidence, and a structured research memo. No investment advice.",
};

const noFlashScript = `(() => {
  try {
    const stored = localStorage.getItem("openfilingrag-theme");
    const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
    const theme = stored || (prefersDark ? "dark" : "light");
    if (theme === "dark") document.documentElement.classList.add("dark");
    document.documentElement.style.colorScheme = theme;
  } catch (_) {}
})();`;

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // suppressHydrationWarning on <html>/<body>: noFlashScript writes
  // color-scheme to <html> before React hydrates, and browser extensions
  // (Redeviation, Grammarly, …) inject attributes here too — both create
  // by-design SSR/CSR divergence we don't want logged.
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: noFlashScript }} />
      </head>
      <body suppressHydrationWarning>
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
