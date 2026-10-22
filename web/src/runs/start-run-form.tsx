"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent } from "react";

import { createApiClient } from "@/api/client";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

import { sampleSpec } from "./sample-spec";

/** Starts a run of the sample workflow and opens its event page. */
export function StartRunForm({ baseUrl }: { baseUrl?: string }) {
  const router = useRouter();
  const inputId = useId();
  const [input, setInput] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setPending(true);
    setError(null);
    try {
      const { data, response } = await createApiClient(baseUrl).POST("/runs", {
        body: { workflow: sampleSpec, input },
      });
      if (!data) throw new Error(`The API refused the run (HTTP ${response.status}).`);
      router.push(`/runs/${data.run_id}`);
    } catch (err) {
      setError(
        err instanceof TypeError
          ? "Could not reach the API."
          : err instanceof Error
            ? err.message
            : String(err),
      );
      setPending(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Sample run</h2>
        </CardTitle>
        <CardDescription>
          Runs <span className="font-medium text-foreground">{sampleSpec.name}</span>, a one-agent
          workflow.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={inputId}>Input</Label>
            <Input
              id={inputId}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Text for the first agent"
            />
          </div>
          <Button type="submit" disabled={pending} className="self-start">
            {pending ? "Starting…" : "Start sample run"}
          </Button>
          {error ? (
            <Alert variant="destructive">
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}
        </form>
      </CardContent>
    </Card>
  );
}
