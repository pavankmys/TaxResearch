import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { alertSeverity, alertSeverityLabel } from "@/components/dashboard/alerts";

export interface AlertItem {
  kind: string;
  message: string;
  subject: string | null;
}

/**
 * Alerts that are firing now. Rendered only when there are alerts, so role="alert" is never an
 * empty region. Each alert names its severity in text.
 */
export function AlertsBanner({ alerts }: { alerts: readonly AlertItem[] }) {
  if (alerts.length === 0) {
    return null;
  }
  const hasCritical = alerts.some((alert) => alertSeverity(alert.kind) === "critical");
  const count = alerts.length;

  return (
    <Alert variant={hasCritical ? "destructive" : "default"}>
      <AlertTitle>
        {count === 1 ? "1 alert needs attention" : `${count} alerts need attention`}
      </AlertTitle>
      <AlertDescription>
        <ul className="mt-2 space-y-1">
          {alerts.map((alert, index) => {
            const severity = alertSeverity(alert.kind);
            return (
              <li key={`${alert.kind}-${alert.subject ?? ""}-${index}`} className="flex flex-wrap items-center gap-2">
                <Badge variant={severity === "critical" ? "destructive" : "secondary"}>
                  {alertSeverityLabel(severity)}
                </Badge>
                <span>
                  {alert.message}
                  {alert.subject ? ` (${alert.subject})` : ""}
                </span>
              </li>
            );
          })}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
