import type { components } from "@/api/schema";

/** The one-node workflow the home page starts. Editing specs comes with the canvas. */
export const sampleSpec: components["schemas"]["WorkflowSpec"] = {
  spec_version: "0",
  id: "summarize-readme",
  name: "Summarize the README",
  root: {
    type: "agent",
    id: "summarizer",
    role: "Technical writer",
    instructions: "Read the README and write a five-line summary.",
  },
};
