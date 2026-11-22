import { InfoIcon } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/** A run a trigger started stays on Claude (8.3): says so, and names the agents that asked for
 * Copilot (`provider_fallback`). A notice, not a status. */
export function ProviderFallbackNote({ nodes }: { nodes: string[] }) {
  return (
    <Alert data-testid="provider-fallback">
      <InfoIcon aria-hidden="true" />
      <AlertTitle>Ran on Claude</AlertTitle>
      <AlertDescription>
        <span>A trigger started this run, and triggers stay on Claude.</span>
        {nodes.length > 0 ? (
          <span>
            {" "}
            Agents set to Copilot:{" "}
            {nodes.map((id, i) => (
              <span key={id}>
                {i > 0 ? ", " : ""}
                <span className="font-mono">{id}</span>
              </span>
            ))}
            .
          </span>
        ) : null}
      </AlertDescription>
    </Alert>
  );
}
