"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/** Light, dark or system theme, set as a class on `<html>`. The top bar's theme menu
 * switches it. */
export function ThemeProvider(props: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="class"
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      {...props}
    />
  );
}
