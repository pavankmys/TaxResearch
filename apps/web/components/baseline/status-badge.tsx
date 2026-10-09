import { Badge } from "@/components/ui/badge";

/** Badge for baseline_status. */
export function StatusBadge({ status }: { status: string }) {
  if (status === "verified") {
    return <Badge variant="default">Verified</Badge>;
  }
  if (status === "loaded") {
    return <Badge variant="secondary">Loaded, awaiting verification</Badge>;
  }
  return <Badge variant="outline">Not loaded</Badge>;
}
