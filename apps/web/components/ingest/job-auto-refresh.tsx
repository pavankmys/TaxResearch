"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { JOB_REFRESH_MS } from "@/components/ingest/job-state";

/**
 * Re-renders the job page every few seconds, so the server reads the job again. It is mounted
 * only while the job is still moving, and it stops when the page no longer renders it.
 */
export function JobAutoRefresh() {
  const router = useRouter();

  useEffect(() => {
    const timer = setInterval(() => {
      router.refresh();
    }, JOB_REFRESH_MS);
    return () => clearInterval(timer);
  }, [router]);

  return null;
}
