"use server";

import { revalidatePath } from "next/cache";

import type { VerifyState } from "@/components/baseline/types";
import { messageFromDetail } from "@/components/ingest/payload";
import { apiClient } from "@/lib/server/api";

function errorState(message: string): VerifyState {
  return { outcome: "error", message };
}

/** Verify a baseline after the user confirms they have checked the provision tree. */
export async function verifyBaseline(
  _previous: VerifyState,
  formData: FormData,
): Promise<VerifyState> {
  const code = String(formData.get("code") ?? "");

  // Validate code format
  if (!code || !/^[A-Z0-9_]{1,40}$/.test(code)) {
    return errorState("The instrument code is not valid.");
  }

  const client = await apiClient();
  const { response, error } = await client.POST("/v1/baseline/instruments/{code}/verify", {
    params: { path: { code } },
  });

  if (!response.ok) {
    return errorState(messageFromDetail(error?.detail, "Could not verify the baseline."));
  }

  revalidatePath("/baseline");
  revalidatePath(`/baseline/${code}`);

  return { outcome: "verified", message: "Baseline verified successfully." };
}
