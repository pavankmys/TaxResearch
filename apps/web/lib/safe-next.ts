/**
 * Return `value` if it is a relative path inside this app, otherwise `fallback`.
 * Blocks absolute URLs, protocol-relative "//host" and backslash tricks such as "/\host".
 */
export function safeNext(value: string | null | undefined, fallback = "/queue"): string {
  if (!value) {
    return fallback;
  }
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return fallback;
  }
  if (/[\u0000-\u001f\u007f\\]/.test(value)) {
    return fallback;
  }
  return value;
}
