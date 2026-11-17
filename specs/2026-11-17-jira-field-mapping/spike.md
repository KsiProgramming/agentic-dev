# Spike: a real site's field list (7.4)

Run on 2026-11-17 against the Jira Cloud site the dev stack is connected to, with the stored grant (`read:jira-work`), read-only: `GET /rest/api/3/field`, `GET /rest/api/3/project/KAN` and `GET /rest/api/3/issue/KAN-1?fields=*all`. The script printed ids, names and schemas only, never a token or a field's content.

## Found

- `/rest/api/3/field` answers one JSON list of 51 fields, system and custom together, each with `id`, `name`, `custom` and `schema` (`type`, then `system` for a system field or `custom` for a custom one, e.g. `com.atlassian.jira.plugin.system.customfieldtypes:datepicker`). Three entries have no `schema` at all; the client reads them as type `""`, which fits no role.
- The scope `read:jira-work` is enough for it: no admin scope, and `read:jira-user` played no part.
- Number fields on the site are all system time-tracking fields (`timeestimate`, `timeoriginalestimate`, …, `custom: false`): a filter on `schema.type == "number"` alone would offer them as story points. Hence `JiraField.fits` requires `custom`.
- String custom fields include Jira Software's `jsw-issue-color`, which must not be offered as acceptance criteria. Hence the acceptance-criteria role takes the `textarea` and `textfield` kinds only.
- The only project, `KAN`, is team-managed (`style: next-gen`, `simplified: true`) and on the Kanban template: it has **no** acceptance-criteria field and **no** story-points field. A Kanban board has no estimation field; "Story point estimate" comes with a Scrum project or when estimation is turned on.
- `KAN-1` holds two non-null custom values, both strings (`customfield_10000`, the development summary, and `customfield_10019`, the rank).

## Not yet seen, and what we built on

The site has no field of either role, so the shape of one could not be read here. The code follows Jira's documented shapes, which the fake (`FAKE_FIELDS`) and `packages/jira/tests/test_fields.py` reproduce:

- a paragraph custom field: `schema {type: "string", custom: "…customfieldtypes:textarea"}`, its value ADF on REST API v3;
- a short text: `…:textfield`, its value a string;
- story points: `schema {type: "number", custom: "com.pyxis.greenhopper.jira:jsw-story-points"}` ("Story point estimate", team-managed) or `…:float` ("Story Points", company-managed);
- a team-managed project's own field carries `scope {type: "PROJECT", project: {id}}`.

**To confirm in the real run (plan group 7):** add an "Acceptance criteria" paragraph field and "Story point estimate" to `KAN` (or a Scrum project), run the spike again, and check the scope and value shapes above. Record any difference here and in tech-stack.
