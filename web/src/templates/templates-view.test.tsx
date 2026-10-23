import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";

import {
  CLAUDE,
  CONNECTIONS_PATH,
  DOCS_TEMPLATE,
  GITHUB,
  json,
  noGithub,
  renderWithQueries,
  REPOS,
  REPOS_PATH,
  requested,
  stubApi,
  type Routes,
} from "@/testing/api";
import { DEFAULT_WORKSPACE_ID } from "@/workspace";

import { TemplatesView } from "./templates-view";

const navigation = vi.hoisted(() => ({
  search: new URLSearchParams(),
  replace: vi.fn(),
  push: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => navigation.search,
  usePathname: () => "/templates",
  useRouter: () => ({ replace: navigation.replace, push: navigation.push }),
}));

const RUN_ID = "00000000-0000-0000-0000-0000000000a1";

beforeEach(() => {
  navigation.search = new URLSearchParams();
  navigation.replace.mockReset();
  navigation.push.mockReset();
  window.localStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function connected(extra: Routes = {}): Routes {
  return {
    "GET /templates": () => json(200, [DOCS_TEMPLATE]),
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE, GITHUB]),
    [`GET ${REPOS_PATH}`]: () => json(200, REPOS),
    ...extra,
  };
}

function show(template?: string) {
  if (template) navigation.search = new URLSearchParams({ template });
  return renderWithQueries(<TemplatesView baseUrl="http://api.test" />);
}

function sheet() {
  return within(screen.getByTestId("new-run-sheet"));
}

async function pickRepo(name: string) {
  fireEvent.click(await sheet().findByRole("combobox", { name: "Repository" }));
  fireEvent.click(await screen.findByRole("option", { name: new RegExp(name) }));
}

test("the gallery shows each template with the connections it requires", async () => {
  stubApi({ ...connected(), [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE]) });
  show();

  const card = within(await screen.findByTestId("template-card"));
  expect(card.getByRole("heading", { name: "Generate docs" })).toBeDefined();
  expect(card.getByText("Claude").parentElement?.textContent).toContain("connected");
  expect(card.getByText("GitHub").parentElement?.textContent).toContain("not connected");

  fireEvent.click(card.getByRole("button", { name: /Start/ }));
  expect(navigation.replace).toHaveBeenCalledWith("/templates?template=generate-docs", {
    scroll: false,
  });
});

test("a missing connection is listed before you start, and Start run stays disabled", async () => {
  stubApi({
    ...connected(),
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, []),
    [`GET ${REPOS_PATH}`]: noGithub,
  });
  show("generate-docs");

  const checklist = within(await sheet().findByTestId("connection-checklist"));
  await waitFor(() =>
    expect(checklist.getAllByText("Not connected", { exact: false })).toHaveLength(2),
  );
  expect(checklist.getByRole("button", { name: "Add key" })).toBeDefined();
  expect(checklist.getByRole("button", { name: "Connect GitHub" })).toBeDefined();
  expect(sheet().queryByRole("combobox", { name: "Repository" })).toBeNull();
  expect(sheet().getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
});

test("connecting GitHub from the sheet comes back to it", async () => {
  const fetch = stubApi({
    ...connected(),
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, [CLAUDE]),
    [`POST ${CONNECTIONS_PATH}/github/install`]: () => json(200, { install_url: "https://gh" }),
  });
  const assign = vi.fn();
  vi.stubGlobal("location", { ...window.location, assign });
  show("generate-docs");

  fireEvent.click(await sheet().findByRole("button", { name: "Connect GitHub" }));

  await waitFor(() => expect(assign).toHaveBeenCalledWith("https://gh"));
  const install = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(await install?.json()).toEqual({ return_to: "/templates?template=generate-docs" });
});

test("a Claude key entered in the sheet unlocks Start run", async () => {
  let stored = [GITHUB];
  stubApi({
    ...connected(),
    [`GET ${CONNECTIONS_PATH}`]: () => json(200, stored),
    [`PUT ${CONNECTIONS_PATH}/claude`]: () => {
      stored = [CLAUDE, GITHUB];
      return json(200, CLAUDE);
    },
  });
  show("generate-docs");

  fireEvent.click(await sheet().findByRole("button", { name: "Add key" }));
  fireEvent.change(sheet().getByLabelText("Claude API key"), {
    target: { value: "sk-ant-test-1234" },
  });
  fireEvent.click(sheet().getByRole("button", { name: "Save key" }));

  await pickRepo("acme/web");
  await waitFor(() =>
    expect(sheet().getByRole("button", { name: "Start run" })).toHaveProperty("disabled", false),
  );
});

test("starting sends the template, its options and the repo, then opens the run", async () => {
  const fetch = stubApi(connected({ "POST /runs": () => json(201, { run_id: RUN_ID }) }));
  show("generate-docs");

  await pickRepo("acme/web");
  fireEvent.change(sheet().getByLabelText("Include (optional)"), {
    target: { value: "packages/*\nweb" },
  });
  fireEvent.click(sheet().getByRole("button", { name: "Start run" }));

  await waitFor(() => expect(navigation.push).toHaveBeenCalledWith(`/runs/${RUN_ID}`));
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(await post?.json()).toEqual({
    template: {
      id: "generate-docs",
      parameters: { output_dir: "docs", include: ["packages/*", "web"] },
    },
    input: "",
    repo: { url: "https://github.com/acme/web" },
    workspace_id: DEFAULT_WORKSPACE_ID,
    budget_usd: null,
  });
  expect(window.localStorage.getItem(`agentic:last-repo:${DEFAULT_WORKSPACE_ID}`)).toBe(
    "https://github.com/acme/web",
  );
});

test("the last used repo is preselected while it is still listed", async () => {
  window.localStorage.setItem(
    `agentic:last-repo:${DEFAULT_WORKSPACE_ID}`,
    "https://github.com/acme/api",
  );
  stubApi(connected());
  show("generate-docs");

  expect((await sheet().findByRole("combobox", { name: "Repository" })).textContent).toContain(
    "acme/api",
  );
});

test("a repo is required, and option limits are checked before calling the API", async () => {
  const fetch = stubApi(connected());
  show("generate-docs");
  await sheet().findByRole("combobox", { name: "Repository" });

  fireEvent.change(sheet().getByLabelText("Output dir (optional)"), {
    target: { value: "my docs" },
  });
  fireEvent.click(sheet().getByRole("button", { name: "Start run" }));

  const alerts = await sheet().findAllByRole("alert");
  expect(alerts.map((a) => a.textContent)).toEqual([
    "Pick a repository.",
    "This is not in the expected format.",
  ]);
  expect(requested(fetch)).not.toContain("POST /runs");
});

test("an option the server refuses is shown on its field", async () => {
  stubApi(
    connected({
      "POST /runs": () =>
        json(422, {
          detail: [
            {
              loc: ["body"],
              msg: "Value error, parameters.output_dir: must not contain `.` or `..` segments",
            },
          ],
        }),
    }),
  );
  show("generate-docs");

  await pickRepo("acme/web");
  fireEvent.change(sheet().getByLabelText("Output dir (optional)"), {
    target: { value: "../up" },
  });
  fireEvent.click(sheet().getByRole("button", { name: "Start run" }));

  expect((await sheet().findByRole("alert")).textContent).toBe(
    "must not contain `.` or `..` segments",
  );
  expect(sheet().getByLabelText("Output dir (optional)").getAttribute("aria-invalid")).toBe("true");
});

test("a template whose options cannot be shown says so instead of a partial form", async () => {
  stubApi(
    connected({
      "GET /templates": () =>
        json(200, [
          {
            ...DOCS_TEMPLATE,
            parameters: { type: "object", properties: { depth: { type: "integer" } } },
          },
        ]),
    }),
  );
  show("generate-docs");

  expect((await sheet().findByRole("alert")).textContent).toContain("cannot be shown here");
  expect(sheet().getByRole("button", { name: "Start run" })).toHaveProperty("disabled", true);
});

test("an install result from GitHub is shown above the gallery", async () => {
  stubApi(connected());
  navigation.search = new URLSearchParams({ github: "connected" });
  renderWithQueries(<TemplatesView baseUrl="http://api.test" />);

  expect(screen.getByTestId("github-result").textContent).toBe("GitHub App installed.");
});

test("a run's own budget is sent, and a budget the API refuses is shown on its field", async () => {
  const policy = {
    defaults: {},
    overrides: {},
    effective: { budget_usd: 2 },
  };
  const fetch = stubApi(
    connected({
      [`GET /workspaces/${DEFAULT_WORKSPACE_ID}/policy`]: () => json(200, policy),
      "POST /runs": () =>
        json(422, {
          detail: {
            code: "policy_limits",
            message: "The workflow is above the workspace's run limits: …",
            errors: [
              "agent 'writer' at root.steps[0]: model 'x' has no price, so the budget cannot be enforced",
            ],
          },
        }),
    }),
  );
  show("generate-docs");

  await pickRepo("acme/web");
  const budget = sheet().getByLabelText("Budget (USD)");
  await waitFor(() => expect(budget.getAttribute("placeholder")).toBe("$2.00"));
  fireEvent.change(budget, { target: { value: "0.5" } });
  fireEvent.click(sheet().getByRole("button", { name: "Start run" }));

  expect(await sheet().findByText(/model 'x' has no price/)).toBeDefined();
  const post = fetch.mock.calls.find(([r]) => r.method === "POST")?.[0];
  expect(((await post?.json()) as { budget_usd: number }).budget_usd).toBe(0.5);
  expect(navigation.push).not.toHaveBeenCalled();
});
