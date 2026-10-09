import type { components } from "@/lib/api-client/schema";

export type InstrumentOut = components["schemas"]["InstrumentOut"];
export type InstrumentList = components["schemas"]["InstrumentList"];
export type ProvisionRow = components["schemas"]["ProvisionRow"];
export type ProvisionsList = components["schemas"]["ProvisionsList"];
export type ProvisionDetail = components["schemas"]["ProvisionDetail"];

/** Result of a Server Action that verifies the baseline. Errors are returned, never thrown. */
export interface VerifyState {
  outcome: "idle" | "verified" | "error";
  message: string;
}
