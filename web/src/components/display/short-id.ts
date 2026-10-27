/** The first 8 characters of an id: enough to tell runs apart on a page. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}
