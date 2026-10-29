// Colour comes from semantic tokens only (tech-stack.md → UI design system → "How the rules are
// enforced"). This rule rejects, in any string or template literal in `src`:
// - Tailwind palette classes: `bg-red-100`, `text-indigo-600`, `hover:border-zinc-200/50`,
//   `bg-black/10`;
// - arbitrary colour values: `bg-[#4f46e5]`, `text-[oklch(0.5_0.2_270)]`, `shadow-[0_1px_rgb(…)]`;
// - colour literals: `"#4f46e5"`, `"rgb(0 0 0)"`, `"oklch(0.5 0.2 270)"`.
// A new colour is a token in `src/app/globals.css` (light and dark), which is not linted.
// It also rejects arbitrary text sizes (`text-[13px]`, `leading-[1.1rem]`): sizes come from the
// type scale (`text-caption` … `text-stat`, `text-kbd`). Sizes relative to the parent (`em`) and
// `text-[0px]` (a visually hidden count) are allowed.

const PALETTE =
  "slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose";
const UTILITY =
  "bg|text|border(?:-[xytrbls])?|ring(?:-offset)?|outline|fill|stroke|from|via|to|decoration|shadow|inset-shadow|divide|placeholder|caret|accent";
// `color(` only counts inside brackets: in plain text it is too often a word ("a color(s)").
const COLOR_FUNCTION = "(?:rgba?|hsla?|hwb|oklch|oklab|lch|lab)\\(";

const CHECKS = [
  {
    pattern: new RegExp(
      `(?:^|[\\s:!"'\`])(?:${UTILITY})-(?:(?:${PALETTE})-\\d{2,3}|black|white)(?![\\w-])`,
    ),
    message: "Palette colour class",
  },
  {
    pattern: new RegExp(`-\\[[^\\]]*(?:#[0-9a-fA-F]{3,8}|color\\(|${COLOR_FUNCTION})`),
    message: "Arbitrary colour value",
  },
  {
    pattern: new RegExp(`^\\s*#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\\s*$`),
    message: "Hex colour",
  },
  {
    pattern: new RegExp(`(?:^|[\\s,(])${COLOR_FUNCTION}`),
    message: "Colour function",
  },
  {
    pattern: /(?:^|[\s:!"'`])(?:text|leading)-\[(?!0px\])[\d.]+(?:px|rem)\]/,
    message: "Arbitrary text size",
  },
];

/** @type {import("eslint").Rule.RuleModule} */
const noRawColors = {
  meta: {
    type: "problem",
    docs: {
      description:
        "Colour comes from semantic tokens (bg-background, text-status-failed) and text sizes from the type scale only.",
    },
    messages: {
      raw: "{{kind}} `{{text}}`: use a semantic token (bg-primary, text-muted-foreground, bg-status-failed-muted) or a type-scale size (text-meta). A new colour or size is a token in src/app/globals.css.",
    },
    schema: [],
  },
  create(context) {
    function check(node, value) {
      for (const { pattern, message } of CHECKS) {
        const match = pattern.exec(value);
        if (match) {
          context.report({
            node,
            messageId: "raw",
            data: { kind: message, text: match[0].trim() },
          });
          return;
        }
      }
    }
    return {
      Literal(node) {
        if (typeof node.value === "string") check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.cooked ?? node.value.raw);
      },
    };
  },
};

const plugin = {
  meta: { name: "agentic-ui" },
  rules: { "no-raw-colors": noRawColors },
};

export default plugin;
