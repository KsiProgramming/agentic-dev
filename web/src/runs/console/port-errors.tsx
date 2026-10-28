"use client";

import { BracesIcon } from "lucide-react";
import { useId, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

import type { PortFailure } from "../timeline";

/** Errors shown before "Show all". */
const SHOWN = 5;

function NodeId({ id }: { id: string }) {
  return <span className="font-mono">{id}</span>;
}

/**
 * Why a typed port (4.2) failed the step: which side, and each place the JSON went wrong (its
 * pointer in mono, the message as text). Not an `alert` itself: the run's banner announces the
 * failure once.
 */
export function PortErrors({ stepId, port }: { stepId: string; port: PortFailure }) {
  const [all, setAll] = useState(false);
  const id = useId();
  const shown = all ? port.errors : port.errors.slice(0, SHOWN);
  return (
    <Alert variant="destructive" role={undefined} data-testid="port-errors">
      <BracesIcon aria-hidden="true" />
      <AlertTitle>Wrong shape</AlertTitle>
      <AlertDescription className="flex min-w-0 flex-col gap-2 text-meta">
        <p>
          {port.side === "output" ? (
            <>
              The output of <NodeId id={stepId} /> does not match its output schema.
            </>
          ) : port.fromNodeId ? (
            <>
              The input from <NodeId id={port.fromNodeId} /> does not match the input schema of{" "}
              <NodeId id={stepId} />.
            </>
          ) : (
            <>
              The input of <NodeId id={stepId} /> does not match its input schema.
            </>
          )}
        </p>
        <ul id={id} className="flex min-w-0 flex-col gap-1">
          {shown.map((error, i) => (
            <li key={i} className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span className="font-mono break-all text-foreground">
                {error.pointer || "(top level)"}
              </span>
              <span className="min-w-0 break-words">{error.message}</span>
            </li>
          ))}
        </ul>
        {port.errors.length > SHOWN ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="w-fit"
            aria-expanded={all}
            aria-controls={id}
            onClick={() => setAll((a) => !a)}
          >
            {all ? "Show fewer" : `Show all ${port.errors.length}`}
          </Button>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
