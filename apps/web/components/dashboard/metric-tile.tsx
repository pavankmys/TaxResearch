import { Card } from "@/components/ui/card";

interface MetricTileProps {
  label: string;
  value: string;
  detail?: string;
}

/** One number with a text label. The label is always shown, never only as a colour or icon. */
export function MetricTile({ label, value, detail }: MetricTileProps) {
  return (
    <Card className="p-4">
      <dl className="space-y-1">
        <dt className="text-sm font-medium text-muted-foreground">{label}</dt>
        <dd className="text-2xl font-semibold tabular-nums">{value}</dd>
        {detail ? <dd className="text-xs text-muted-foreground">{detail}</dd> : null}
      </dl>
    </Card>
  );
}
