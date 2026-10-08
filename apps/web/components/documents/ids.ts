const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function isUuid(value: string): boolean {
  return UUID_PATTERN.test(value);
}

/** The first eight characters of an ID, for places where a full UUID is too long to read. */
export function shortId(value: string): string {
  return value.slice(0, 8);
}
