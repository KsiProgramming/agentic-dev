"use client";

import {
  ChevronsUpDownIcon,
  CircleUserRoundIcon,
  MonitorIcon,
  MoonIcon,
  Rows3Icon,
  Rows4Icon,
  SunIcon,
} from "lucide-react";
import { useTheme } from "next-themes";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

import { useCompact } from "./use-density";

const THEMES = [
  { value: "light", label: "Light", icon: SunIcon },
  { value: "dark", label: "Dark", icon: MoonIcon },
  { value: "system", label: "System", icon: MonitorIcon },
] as const;

const DENSITIES = [
  { value: "comfortable", label: "Comfortable", icon: Rows3Icon },
  { value: "compact", label: "Compact", icon: Rows4Icon },
] as const;

/**
 * The user menu at the bottom of the sidebar: this browser's theme and row density. There are
 * no accounts yet, so it holds preferences only. `rail` shows just its icon from 1024 to 1279 px.
 */
export function UserMenu({ rail = false }: { rail?: boolean }) {
  const { theme, setTheme } = useTheme();
  const [compact, setCompact] = useCompact();
  const railHidden = rail ? "lg:max-xl:sr-only" : undefined;
  const trigger = (
    <DropdownMenuTrigger
      className={cn(
        "flex h-9 w-full items-center gap-2.5 rounded-md px-2.5 font-medium text-muted-foreground transition-colors outline-none hover:bg-muted hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring/50 data-[state=open]:bg-muted data-[state=open]:text-foreground",
        rail && "lg:max-xl:justify-center",
      )}
    >
      <CircleUserRoundIcon aria-hidden="true" className="size-4 shrink-0" />
      <span className={railHidden}>Preferences</span>
      <ChevronsUpDownIcon
        aria-hidden="true"
        className={cn("ml-auto size-4 shrink-0", rail && "lg:max-xl:hidden")}
      />
    </DropdownMenuTrigger>
  );
  return (
    // Not modal: a modal menu hides the page with `aria-hidden` while its scroll areas stay
    // focusable (axe `aria-hidden-focus`). Escape and a click outside still close it.
    <DropdownMenu modal={false}>
      {rail ? (
        <Tooltip>
          <TooltipTrigger asChild>{trigger}</TooltipTrigger>
          {/* Only the rail needs a label on hover: the full sidebar shows it. */}
          <TooltipContent side="right" sideOffset={8} className="xl:hidden">
            Preferences
          </TooltipContent>
        </Tooltip>
      ) : (
        trigger
      )}
      <DropdownMenuContent side="top" align="start" className="w-56">
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
          {THEMES.map(({ value, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon aria-hidden="true" />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Density</DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={compact ? "compact" : "comfortable"}
          onValueChange={(value) => setCompact(value === "compact")}
        >
          {DENSITIES.map(({ value, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon aria-hidden="true" />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
