"use client";

import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "cn";
import { Tabs as TabsPrimitive } from "radix-ui";

// design-language.md → Components. `line` (the default) is underline tabs: 36 px, 13 px weight
// 500, the selected tab in `foreground` with a 2 px `primary` bar over the row's bottom edge, the
// others in `foreground-secondary`. `segmented` is only for a view of the same data or a two-way
// choice in a form. The row's edge is an inset shadow, so the bar can cover it inside the scroll box.
const tabsListVariants = cva("", {
  variants: {
    variant: {
      line: "no-scrollbar flex h-9 w-full max-w-full items-stretch gap-5 overflow-x-auto shadow-[inset_0_-1px_0_var(--border)]",
      segmented:
        "inline-flex h-9 w-fit items-center gap-1 rounded-lg bg-muted p-1 text-foreground-secondary",
    },
  },
  defaultVariants: { variant: "line" },
});

const tabsTriggerVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 text-meta font-medium whitespace-nowrap transition-colors outline-none disabled:pointer-events-none disabled:opacity-50 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        line: "relative px-0.5 text-foreground-secondary after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-primary after:opacity-0 hover:text-foreground focus-visible:-outline-offset-2 data-[state=active]:text-foreground data-[state=active]:after:opacity-100 aria-[current=page]:text-foreground aria-[current=page]:after:opacity-100",
        segmented:
          "h-7 rounded-md px-2.5 hover:text-foreground data-[state=active]:bg-background data-[state=active]:text-foreground data-[state=active]:shadow-xs aria-[current=page]:bg-background aria-[current=page]:text-foreground aria-[current=page]:shadow-xs",
      },
    },
    defaultVariants: { variant: "line" },
  },
);

type TabsVariant = NonNullable<VariantProps<typeof tabsListVariants>["variant"]>;

const TabsVariantContext = React.createContext<TabsVariant>("line");

function Tabs({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col gap-3", className)}
      {...props}
    />
  );
}

/** Fades the row's end while more tabs are hidden to the side (design-language.md → Mobile). */
function useEdgeFade<T extends HTMLElement>() {
  const ref = React.useRef<T>(null);
  const [fade, setFade] = React.useState(false);
  React.useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const update = () =>
      setFade(element.scrollWidth - element.clientWidth - element.scrollLeft > 1);
    update();
    element.addEventListener("scroll", update, { passive: true });
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    observer?.observe(element);
    return () => {
      element.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  }, []);
  const style: React.CSSProperties | undefined = fade
    ? { maskImage: "linear-gradient(to right, black calc(100% - 2rem), transparent)" }
    : undefined;
  return { ref, style };
}

function TabsList({
  className,
  variant = "line",
  style,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & VariantProps<typeof tabsListVariants>) {
  const { ref, style: fadeStyle } = useEdgeFade<HTMLDivElement>();
  const resolved = variant ?? "line";
  return (
    <TabsVariantContext.Provider value={resolved}>
      <TabsPrimitive.List
        ref={ref}
        data-slot="tabs-list"
        data-variant={resolved}
        className={cn(tabsListVariants({ variant: resolved }), className)}
        style={{ ...fadeStyle, ...style }}
        {...props}
      />
    </TabsVariantContext.Provider>
  );
}

function TabsTrigger({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  const variant = React.useContext(TabsVariantContext);
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(tabsTriggerVariants({ variant }), className)}
      {...props}
    />
  );
}

function TabsContent({ className, ...props }: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("min-w-0 outline-none", className)}
      {...props}
    />
  );
}

export {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  tabsListVariants,
  tabsTriggerVariants,
  useEdgeFade,
};
