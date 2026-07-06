const TIMEZONE_SUFFIX_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/i;

export function parseBackendDate(value: string | Date | null | undefined): Date | null {
  if (!value) return null;
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const trimmed = value.trim();
  if (!trimmed) return null;

  // Backend datetime values are currently stored as UTC but often serialized
  // without a timezone suffix. Browsers interpret timezone-less ISO strings as
  // local time, which makes KST screens show UTC clock values. Treat those
  // values as UTC explicitly.
  const normalized = TIMEZONE_SUFFIX_PATTERN.test(trimmed) ? trimmed : `${trimmed}Z`;
  const parsed = new Date(normalized);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatKstDateTime(value: string | Date | null | undefined): string {
  const parsed = parseBackendDate(value);
  if (!parsed) return "-";

  return new Intl.DateTimeFormat("ko-KR", {
    dateStyle: "short",
    timeStyle: "short",
    timeZone: "Asia/Seoul",
  }).format(parsed);
}
