import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/** The props react-markdown passes, without its `node` (not a DOM attribute). */
function plain<P extends { node?: unknown }>(props: P): Omit<P, "node"> {
  const rest = { ...props };
  delete rest.node;
  return rest;
}

/** Markdown elements in the console's quiet style. Links open in a new tab. */
const COMPONENTS: Components = {
  a: (props) => (
    <a
      {...plain(props)}
      target="_blank"
      rel="noreferrer"
      className="text-primary underline underline-offset-4"
    />
  ),
  h1: (props) => <h3 {...plain(props)} className="text-base font-semibold" />,
  h2: (props) => <h4 {...plain(props)} className="text-base font-semibold" />,
  h3: (props) => <h5 {...plain(props)} className="font-semibold" />,
  h4: (props) => <h6 {...plain(props)} className="font-semibold" />,
  ul: (props) => <ul {...plain(props)} className="list-disc pl-5" />,
  ol: (props) => <ol {...plain(props)} className="list-decimal pl-5" />,
  code: (props) => (
    <code {...plain(props)} className="rounded-sm bg-muted px-1 py-0.5 font-mono text-[0.85em]" />
  ),
  pre: (props) => (
    <pre
      {...plain(props)}
      className="overflow-x-auto rounded-md border bg-muted/40 p-3 font-mono text-xs [&_code]:bg-transparent [&_code]:p-0"
    />
  ),
  blockquote: (props) => (
    <blockquote {...plain(props)} className="border-l-2 pl-3 text-muted-foreground" />
  ),
  table: (props) => (
    <div className="overflow-x-auto">
      <table
        {...plain(props)}
        className="text-meta [&_td]:border [&_td]:px-2 [&_th]:border [&_th]:px-2"
      />
    </div>
  ),
};

/**
 * One agent turn's text as Markdown. Raw HTML in it (e.g. `<!-- module: src -->` markers) is
 * dropped, never rendered, and so are images (an image URL would make the browser fetch it): the
 * text is data, not a page.
 */
export function AgentMessage({
  text,
  streaming = false,
  className,
}: {
  text: string;
  streaming?: boolean;
  className?: string;
}) {
  return (
    <div
      data-testid="agent-message"
      data-streaming={streaming || undefined}
      className={cn(
        // Reading text stops at 72 characters; code blocks and tables use the whole width.
        "flex min-w-0 flex-col gap-2 text-body break-words *:max-w-prose [&_p]:whitespace-pre-wrap [&>div]:max-w-none [&>pre]:max-w-none",
        className,
      )}
    >
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={COMPONENTS}
        disallowedElements={["img"]}
        skipHtml
      >
        {text}
      </Markdown>
      {streaming ? (
        <span
          aria-hidden="true"
          className="-mt-2 inline-block h-4 w-1.5 bg-muted-foreground/60 motion-safe:animate-pulse"
        />
      ) : null}
    </div>
  );
}
