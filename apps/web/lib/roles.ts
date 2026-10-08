/** Roles that may use the reviewer console (TSD 8.1). Other users see "No access". */
export const REVIEWER_ROLES: readonly string[] = ["platform_admin", "platform_content_editor"];

export function isReviewer(roles: readonly string[]): boolean {
  return roles.some((role) => REVIEWER_ROLES.includes(role));
}
