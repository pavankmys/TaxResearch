import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/** Shown in place of a page's data when the API call fails. The page itself still renders. */
export function LoadFailed({ what, status }: { what: string; status: number }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{`Could not load ${what}`}</AlertTitle>
      <AlertDescription>
        {`The API answered with HTTP ${status}. Reload the page to try again.`}
      </AlertDescription>
    </Alert>
  );
}
