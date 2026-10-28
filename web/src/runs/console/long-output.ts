/** An answer longer than this is capped (about 480 px) with "Show full output". */
const LONG_CHARS = 1200;
const LONG_LINES = 20;

export function isLongOutput(text: string): boolean {
  return text.length > LONG_CHARS || text.split("\n").length > LONG_LINES;
}
