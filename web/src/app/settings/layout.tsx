import { PageHeader } from "@/components/page-header";
import { SettingsNav } from "@/settings/settings-nav";

/** Every settings sub-page: the page header, the secondary nav beside the page from `md` (above
 * it below that), then the sub-page's short stack of cards. */
export default function SettingsLayout({ children }: LayoutProps<"/settings">) {
  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        title="Settings"
        description="Model access, the repositories this workspace can work on, what its runs cost and how far they may go."
      />
      <div className="flex flex-col gap-6 md:flex-row md:items-start">
        <div className="md:sticky md:top-20 md:w-52 md:shrink-0">
          <SettingsNav />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-6">{children}</div>
      </div>
    </div>
  );
}
