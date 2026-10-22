"use client";

import { MenuIcon } from "lucide-react";
import { Suspense, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { TooltipProvider } from "@/components/ui/tooltip";

import { Breadcrumbs } from "./breadcrumbs";
import { Sidebar } from "./sidebar";
import { ThemeMenu } from "./theme-menu";

/** The sidebar as a drawer, below `lg` (1024 px). Following a link closes it. */
function MobileNav({ baseUrl }: { baseUrl?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <Sheet open={open} onOpenChange={setOpen}>
      <SheetTrigger asChild>
        <Button type="button" variant="ghost" size="icon" aria-label="Open navigation">
          <MenuIcon aria-hidden="true" />
        </Button>
      </SheetTrigger>
      <SheetContent side="left" className="w-64 p-0" aria-describedby={undefined}>
        <SheetTitle className="sr-only">Navigation</SheetTitle>
        <Sidebar onNavigate={() => setOpen(false)} baseUrl={baseUrl} />
      </SheetContent>
    </Sheet>
  );
}

/**
 * The frame around every page (tech-stack.md → UI design system → Layout): a sidebar with the
 * main sections and a top bar with breadcrumbs and the theme menu. The sidebar is full from
 * 1280 px, an icon rail from 1024 px and a drawer below that.
 */
export function AppShell({ children, baseUrl }: { children: ReactNode; baseUrl?: string }) {
  return (
    <TooltipProvider>
      <a
        href="#content"
        className="sr-only rounded-md bg-background px-3 py-2 font-medium shadow-sm ring-1 ring-border focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50"
      >
        Skip to content
      </a>
      <div data-testid="app-shell" className="flex min-h-svh">
        {/* The border spans the whole page; the sidebar itself stays in view while it scrolls. */}
        <aside aria-label="Sidebar" className="hidden shrink-0 border-r lg:block lg:w-16 xl:w-60">
          <div className="sticky top-0 h-svh">
            <Sidebar rail baseUrl={baseUrl} />
          </div>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-40 flex h-14 items-center gap-2 border-b bg-background px-4 md:px-6">
            <div className="lg:hidden">
              <MobileNav baseUrl={baseUrl} />
            </div>
            {/* Breadcrumbs read the path, which is unknown for a run while the shell prerenders. */}
            <Suspense fallback={<div className="flex-1" />}>
              <Breadcrumbs className="flex-1" />
            </Suspense>
            <div className="ml-auto">
              <ThemeMenu />
            </div>
          </header>
          {/* `min-w-0` lets wide content (tables, JSON) scroll in its own box, not the page. */}
          <main
            id="content"
            tabIndex={-1}
            className="min-w-0 flex-1 px-4 py-6 outline-none md:px-6"
          >
            {children}
          </main>
        </div>
      </div>
    </TooltipProvider>
  );
}
