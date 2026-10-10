import { SearchBar, type CitationMatch } from "@/components/search/search-bar";
import { SearchFilters } from "@/components/search/search-filters";
import { SearchResults } from "@/components/search/search-results";
import { LoadFailed } from "@/components/dashboard/load-failed";
import { apiClient } from "@/lib/server/api";
import type { components } from "@/lib/api-client/schema";

export const metadata = { title: "Search - TaxResearch Console" };

type SearchResponse = components["schemas"]["SearchResponse"];
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

function first(value: string | string[] | undefined): string {
  return Array.isArray(value) ? (value[0] ?? "") : (value ?? "");
}

function all(value: string | string[] | undefined): string[] {
  if (!value) return [];
  if (Array.isArray(value)) return value;
  return value.includes(",") ? value.split(",") : [value];
}

function getTodayIST(): string {
  const now = new Date();
  const utc = now.getTime() + now.getTimezoneOffset() * 60000;
  const ist = new Date(utc + 3600000 * 5.5);
  return ist.toISOString().split("T")[0];
}

export default async function SearchPage({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const q = first(params.q).trim();
  const asOnParam = first(params.as_on);
  const asOn = asOnParam || getTodayIST();
  const types = all(params.types);
  const court = first(params.court) || undefined;
  const state = first(params.state) || undefined;
  const dateFrom = first(params.date_from) || undefined;
  const dateTo = first(params.date_to) || undefined;
  const expand = params.expand !== "false";
  const limit = Math.min(Math.max(Number.parseInt(first(params.limit) || "20", 10), 1), 100);
  const offset = Math.max(Number.parseInt(first(params.offset) || "0", 10), 0);

  const client = await apiClient();

  let searchData: SearchResponse | null = null;
  let searchStatus: number = 200;
  let citationMatch: CitationMatch | null = null;

  if (q) {
    const [searchRes, resolveRes] = await Promise.all([
      client.GET("/v1/search", {
        params: {
          query: {
            q,
            as_on: asOn,
            types: types.length > 0 ? types : undefined,
            court,
            state,
            date_from: dateFrom,
            date_to: dateTo,
            expand,
            limit,
            offset,
          },
        },
      }),
      client.GET("/v1/resolve", {
        params: {
          query: { q },
        },
      }),
    ]);

    searchData = searchRes.data ?? null;
    searchStatus = searchRes.response.status;

    if (resolveRes.data && resolveRes.data.matched) {
      citationMatch = resolveRes.data as CitationMatch;
    }
  }

  if (q && !searchData && searchStatus >= 400) {
    return (
      <section className="space-y-6">
        <LoadFailed what="the search results" status={searchStatus} />
      </section>
    );
  }

  return (
    <section className="space-y-6" aria-labelledby="search-title">
      <header className="space-y-1">
        <h1 id="search-title" className="text-2xl font-semibold tracking-tight">
          Tax Corpus Search
        </h1>
        <p className="text-sm text-muted-foreground">
          Bi-temporal point-in-time full-text search across primary acts, subordinate rules,
          notifications, circulars, and judicial precedents.
        </p>
      </header>

      <SearchBar
        initialQuery={q}
        initialAsOn={asOn}
        initialExpand={expand}
        initialCitationMatch={citationMatch}
      />

      {q ? (
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6 items-start">
          <aside className="md:col-span-1">
            <SearchFilters
              selectedTypes={types}
              selectedCourt={court}
              selectedState={state}
              dateFrom={dateFrom}
              dateTo={dateTo}
              groups={searchData?.groups ?? {}}
            />
          </aside>
          <main className="md:col-span-3">
            {searchData ? (
              <SearchResults
                response={searchData}
                limit={limit}
                offset={offset}
              />
            ) : null}
          </main>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed p-12 text-center space-y-3">
          <h2 className="text-lg font-medium text-foreground">
            Search across India&apos;s GST and Tax Corpus
          </h2>
          <p className="text-sm text-muted-foreground max-w-lg mx-auto">
            Enter search keywords (e.g. &ldquo;ITC reversal capital goods&rdquo;) or exact citations
            (e.g. &ldquo;s.16(2)(c)&rdquo;, &ldquo;rule 36(4)&rdquo;, &ldquo;Notf 11/2017-CT(R)&rdquo;).
          </p>
          <div className="flex flex-wrap justify-center gap-2 pt-2">
            {[
              "s.16(2)(c)",
              "rule 36(4)",
              "Notf 11/2017",
              "Circular 183/15/2022",
              "Input tax credit conditions",
              "Reverse charge mechanism",
            ].map((example) => (
              <a
                key={example}
                href={`/search?q=${encodeURIComponent(example)}&as_on=${asOn}`}
                className="rounded-full border bg-muted/40 px-3 py-1 text-xs text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
              >
                {example}
              </a>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
