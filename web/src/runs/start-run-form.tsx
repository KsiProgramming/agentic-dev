"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { createApiClient } from "@/api/client";

import { sampleSpec } from "./sample-spec";

/** Starts a run of the sample workflow and opens its event page. */
export function StartRunForm({ baseUrl }: { baseUrl?: string }) {
  const router = useRouter();
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
    <form onSubmit={onSubmit} className="flex w-full max-w-md flex-col gap-3">
      <p className="text-sm text-gray-600">
        Runs <span className="font-medium">{sampleSpec.name}</span>, a one-agent workflow.
      </p>
      <label className="flex flex-col gap-1 text-sm">
        Input
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Text for the first agent"
          className="rounded border px-2 py-1"
        />
      </label>
      <button
        type="submit"
        disabled={pending}
        className="rounded bg-black px-3 py-1.5 text-white disabled:opacity-50"
      >
        {pending ? "Starting…" : "Start sample run"}
      </button>
      {error ? (
        <p role="alert" className="text-sm text-red-700">
          {error}
        </p>
      ) : null}
    </form>
  );
}
