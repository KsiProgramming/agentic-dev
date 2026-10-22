/** What a map item is called: a string item as is; an object by its `path`, `name` or `id`, with
 * its `kind` if it has one; anything else as JSON. */
export function itemName(item: unknown, index: number): { name: string; kind: string | null } {
  if (typeof item === "string") return { name: item, kind: null };
  if (item && typeof item === "object" && !Array.isArray(item)) {
    const fields = item as Record<string, unknown>;
    const name = [fields.path, fields.name, fields.id].find((v) => typeof v === "string");
    if (typeof name === "string") {
      return { name, kind: typeof fields.kind === "string" ? fields.kind : null };
    }
  }
  if (item === undefined) return { name: `Item ${index + 1}`, kind: null };
  return { name: JSON.stringify(item), kind: null };
}
