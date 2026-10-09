import Link from "next/link";

import { StatusBadge } from "@/components/baseline/status-badge";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { formatDate, formatCount } from "@/components/dashboard/format";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { apiClient } from "@/lib/server/api";

export const metadata = { title: "Baseline" };

export default async function BaselinePage() {
  const client = await apiClient();
  const { data, response } = await client.GET("/v1/baseline/instruments");

  return (
    <section className="space-y-6" aria-labelledby="baseline-title">
      <header className="space-y-2">
        <h1 id="baseline-title" className="text-2xl font-semibold tracking-tight">
          Baseline
        </h1>
        <p className="text-sm text-muted-foreground">
          Check that each instrument was split into the right sections and rules, then verify it.
        </p>
      </header>

      {!data ? (
        <LoadFailed what="the baseline list" status={response.status} />
      ) : (
        <Table>
          <caption className="mb-2 text-left text-sm text-muted-foreground">
            Instruments with baseline status. {data.items.length} shown.
          </caption>
          <TableHeader>
            <TableRow>
              <TableHead scope="col">Instrument</TableHead>
              <TableHead scope="col">Status</TableHead>
              <TableHead scope="col">As on</TableHead>
              <TableHead scope="col">Provisions</TableHead>
              <TableHead scope="col">Sections/Rules</TableHead>
              <TableHead scope="col">Verified by</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {data.items.length === 0 ? (
              <TableRow>
                <TableCell colSpan={6} className="text-muted-foreground">
                  No instruments loaded yet.
                </TableCell>
              </TableRow>
            ) : null}
            {data.items.map((instrument) => (
              <TableRow key={instrument.code}>
                <TableCell className="min-w-48 font-medium">
                  <Link
                    href={`/baseline/${instrument.code}`}
                    className="underline underline-offset-4 hover:no-underline"
                  >
                    {instrument.short_name}
                  </Link>
                  <p className="text-xs text-muted-foreground font-mono">{instrument.code}</p>
                </TableCell>
                <TableCell>
                  <StatusBadge status={instrument.baseline_status} />
                </TableCell>
                <TableCell>{formatDate(instrument.baseline_as_on)}</TableCell>
                <TableCell>{formatCount(instrument.provision_count)}</TableCell>
                <TableCell>{formatCount(instrument.section_count)}</TableCell>
                <TableCell>
                  {instrument.baseline_verified_by_name ? (
                    <>
                      <div>{instrument.baseline_verified_by_name}</div>
                      <div className="text-xs text-muted-foreground">
                        {formatDate(instrument.baseline_verified_at)}
                      </div>
                    </>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
