/** The locale and time zone dates and numbers are shown in (tech-stack.md → UI design system →
 * Display values). The browser's own until the workspace has a setting for them; that setting
 * will pin them here. */
export interface DisplayLocale {
  locale: string;
  timeZone: string;
}

let pinned: DisplayLocale | null = null;
const formats = new Map<string, Intl.NumberFormat | Intl.DateTimeFormat>();

export function displayLocale(): DisplayLocale {
  if (pinned) return pinned;
  const { locale, timeZone } = new Intl.DateTimeFormat().resolvedOptions();
  return { locale, timeZone };
}

/** Shows every value in `value` from now on, or in the browser's locale again with `null`. */
export function pinDisplayLocale(value: DisplayLocale | null): void {
  pinned = value;
  formats.clear();
}

/** A number format in the display locale, made once per locale and options. */
export function numberFormat(options: Intl.NumberFormatOptions = {}): Intl.NumberFormat {
  const { locale } = displayLocale();
  const key = `n|${locale}|${JSON.stringify(options)}`;
  let format = formats.get(key) as Intl.NumberFormat | undefined;
  if (!format) {
    format = new Intl.NumberFormat(locale, options);
    formats.set(key, format);
  }
  return format;
}

/** A date format in the display locale and time zone, made once per locale and options. The
 * locale decides between 12- and 24-hour time. */
export function dateFormat(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const { locale, timeZone } = displayLocale();
  const key = `d|${locale}|${timeZone}|${JSON.stringify(options)}`;
  let format = formats.get(key) as Intl.DateTimeFormat | undefined;
  if (!format) {
    format = new Intl.DateTimeFormat(locale, { timeZone, ...options });
    formats.set(key, format);
  }
  return format;
}
