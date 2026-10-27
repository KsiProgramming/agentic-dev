import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";

import { QueryProvider } from "@/components/query-provider";
import { AppShell } from "@/components/shell/app-shell";
import { DENSITY_SCRIPT } from "@/components/shell/density";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";

import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const jetbrainsMono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains-mono" });

export const metadata: Metadata = {
  title: { default: "Agentic Dev", template: "%s · Agentic Dev" },
  description: "Design, run and trust AI agent workflows on your repositories.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // next-themes sets the theme class before React hydrates, the head script the density class.
    <html lang="en" suppressHydrationWarning className={cn(inter.variable, jetbrainsMono.variable)}>
      <head>
        {/* Compact mode, before the first paint (the density toggle keeps it in localStorage). */}
        <script dangerouslySetInnerHTML={{ __html: DENSITY_SCRIPT }} />
      </head>
      <body>
        <ThemeProvider>
          <QueryProvider>
            <AppShell>{children}</AppShell>
          </QueryProvider>
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
