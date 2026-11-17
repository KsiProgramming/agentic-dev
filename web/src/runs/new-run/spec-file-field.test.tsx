import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, test, vi } from "vitest";

import {
  CLAUDE,
  CONNECTIONS_PATH,
  GITHUB,
  json,
  renderWithQueries,
  REPOS,
  REPOS_PATH,
  stubApi,
} from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { WorkflowRunSheet } from "./new-run-sheet";
import { MAX_SPEC_FILE_BYTES, specFileError, specFileRefusal } from "./spec-file-field";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
});

const RUN_ID = "00000000-0000-0000-0000-0000000000c7";
const SPEC = "# CSV export\n\nAdmins download every order as CSV.\n";

function renderSheet(post: () => Response) {
  const fetch = stubApi({
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE, GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
    "POST /runs": post,
  });
  const navigate = vi.fn();
  renderWithQueries(
    <WorkflowRunSheet
      open
      onOpenChange={() => {}}
      workflow={{
        id: "sdd-spec-file",
        version: 1,
        name: "Build from a spec file",
        requires: ["claude", "github"],
        input: {
          required: true,
          label: "Which spec?",
          description: "Upload a Markdown spec or name one in the repo.",
          example: "docs/spec.md",
          kind: "spec_file",
        },
      }}
      workspaceId={DEFAULT_WORKSPACE_ID}
      baseUrl="http://api.test"
      navigate={navigate}
    />,
  );
  return { fetch, navigate, sheet: within(screen.getByTestId("workflow-run-sheet")) };
}

async function pickRepo(sheet: ReturnType<typeof within>) {
  fireEvent.click(await sheet.findByRole("combobox", { name: "Repository" }));
  fireEvent.click(await screen.findByRole("option", { name: /acme\/web/ }));
}

const posted = (fetch: ReturnType<typeof stubApi>) =>
  fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];

test("an uploaded spec is sent as the run's spec file, with no text input", async () => {
  const { fetch, navigate, sheet } = renderSheet(() => json(202, { run_id: RUN_ID }));
  await pickRepo(sheet);

  expect(sheet.queryByRole("textbox", { name: "Which spec?" })).toBeNull();
  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));
  expect(await sheet.findByText("Pick a Markdown file.")).toBeDefined();
  expect(posted(fetch)).toBeUndefined();

  const file = new File([SPEC], "csv-export.md", { type: "text/markdown" });
  fireEvent.change(sheet.getByLabelText("Which spec?: Markdown file"), {
    target: { files: [file] },
  });
  expect(await sheet.findByText(/^csv-export\.md · /)).toBeDefined();
  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));

  await waitFor(() => expect(navigate).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  expect(await posted(fetch)?.json()).toMatchObject({
    stored_workflow: { id: "sdd-spec-file", version: 1 },
    input: "",
    spec_file: { source: "upload", name: "csv-export.md", content: SPEC },
    repo: { url: "https://github.com/acme/web" },
  });
});

test("a file that is not Markdown is refused before anything is sent", async () => {
  const { fetch, sheet } = renderSheet(() => json(202, { run_id: RUN_ID }));
  await pickRepo(sheet);

  const file = new File([SPEC], "spec.txt", { type: "text/plain" });
  fireEvent.change(sheet.getByLabelText("Which spec?: Markdown file"), {
    target: { files: [file] },
  });
  await sheet.findByText(/^spec\.txt · /);
  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));

  expect(await sheet.findByText("Pick a Markdown file (.md).")).toBeDefined();
  expect(posted(fetch)).toBeUndefined();
});

test("a path in the repo is sent, and the API's refusal is shown on the field", async () => {
  const { fetch, navigate, sheet } = renderSheet(() =>
    json(422, { detail: "path_not_found: docs/spec.md is not in acme/web's default branch" }),
  );
  await pickRepo(sheet);

  const tab = sheet.getByRole("tab", { name: "From the repo" });
  fireEvent.mouseDown(tab);
  fireEvent.click(tab);
  const path = await sheet.findByLabelText("Which spec?: path in the repository");
  expect(path.className).toContain("font-mono");
  expect(path.getAttribute("placeholder")).toBe("e.g. docs/spec.md");
  fireEvent.change(path, { target: { value: "docs/spec.md" } });
  fireEvent.click(sheet.getByRole("button", { name: "Start run" }));

  expect(await sheet.findByText("docs/spec.md is not in acme/web's default branch")).toBeDefined();
  expect(navigate).not.toHaveBeenCalled();
  expect(await posted(fetch)?.json()).toMatchObject({
    input: "",
    spec_file: { source: "repo", path: "docs/spec.md" },
  });
});

test("the checks match the API's rules", () => {
  const upload = { source: "upload" as const, name: "a.md", size: 10, content: "# A", path: "" };
  expect(specFileError(upload)).toBeNull();
  expect(specFileError({ ...upload, name: "A.MARKDOWN" })).toBeNull();
  expect(specFileError({ ...upload, size: MAX_SPEC_FILE_BYTES + 1 })).toBe(
    "This file is over 256 KB.",
  );
  expect(specFileError({ ...upload, content: " \n" })).toBe("This file is empty.");
  const repo = { ...upload, source: "repo" as const, path: "/docs/spec.md" };
  expect(specFileError(repo)).toBeNull();
  expect(specFileError({ ...repo, path: "../spec.md" })).toMatch(/from the repository's root/);
  expect(specFileError({ ...repo, path: "docs/spec.txt" })).toBe("Give a Markdown file (.md).");
  expect(specFileRefusal("not_a_file: docs is not a file in acme/web")).toBe(
    "docs is not a file in acme/web",
  );
  expect(specFileRefusal("issue_invalid: give a key")).toBeNull();
  expect(specFileRefusal(undefined)).toBeNull();
});
