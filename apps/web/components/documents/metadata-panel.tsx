import { ConfidenceBadge } from "@/components/documents/badges";
import { MetadataEditForm } from "@/components/documents/metadata-edit-form";
import { currentFieldValues, EDITABLE_FIELDS } from "@/components/documents/fields";
import { humanFieldName } from "@/components/documents/labels";
import { shortId } from "@/components/documents/ids";
import type { DocumentDetail } from "@/components/documents/types";
import { formatDateTime } from "@/components/dashboard/format";

function asText(value: unknown): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return JSON.stringify(value);
}

interface Override {
  value: unknown;
  by?: string;
  at?: string;
  reason?: string;
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

/** The metadata tab: fields with confidence and overrides, the typed record, and the edit form. */
export function MetadataPanel({ doc }: { doc: DocumentDetail }) {
  const fields = asRecord(doc.metadata.fields);
  const confidence = asRecord(doc.metadata.confidence) as Record<string, number>;
  const overrides = asRecord(doc.metadata.overrides) as Record<string, Override>;
  const names = Object.keys(fields).sort();
  const typedRow = doc.typed_row ? Object.entries(doc.typed_row) : [];

  return (
    <div className="space-y-8">
      <section aria-labelledby="fields-heading" className="space-y-3">
        <h2 id="fields-heading" className="text-lg font-semibold">
          Metadata fields
        </h2>
        <p className="text-sm text-muted-foreground">
          Document confidence {doc.meta_confidence === null ? "is not set" : `${Math.round(doc.meta_confidence * 100)}%`}.
          Reviewer overrides are shown under the field they changed.
        </p>
        {names.length === 0 ? (
          <p className="text-sm text-muted-foreground">No metadata fields recorded yet.</p>
        ) : (
          <dl className="divide-y rounded-md border">
            {names.map((name) => {
              const override = overrides[name];
              return (
                <div key={name} className="grid gap-2 p-3 sm:grid-cols-[12rem_1fr_auto] sm:items-start">
                  <dt className="text-sm font-medium">{humanFieldName(name)}</dt>
                  <dd className="break-words text-sm">
                    <span>{asText(fields[name])}</span>
                    {override ? (
                      <span className="mt-1 block text-xs text-muted-foreground">
                        {`Override: ${override.reason ?? "no reason recorded"} (by ${override.by ? shortId(override.by) : "unknown"}, ${formatDateTime(override.at)})`}
                      </span>
                    ) : null}
                  </dd>
                  <dd>
                    <ConfidenceBadge value={confidence[name]} />
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
      </section>

      <section aria-labelledby="typed-heading" className="space-y-3">
        <h2 id="typed-heading" className="text-lg font-semibold">
          Typed record
        </h2>
        {doc.typed_table ? (
          <>
            <p className="text-sm text-muted-foreground">Row in the {doc.typed_table} table.</p>
            <dl className="divide-y rounded-md border">
              {typedRow.map(([key, value]) => (
                <div key={key} className="grid gap-1 p-3 sm:grid-cols-[12rem_1fr]">
                  <dt className="text-sm font-medium">{humanFieldName(key)}</dt>
                  <dd className="break-words text-sm">{asText(value)}</dd>
                </div>
              ))}
            </dl>
          </>
        ) : (
          <p className="text-sm text-muted-foreground">No typed record for this document type yet.</p>
        )}
      </section>

      <section aria-labelledby="edit-heading" className="space-y-3">
        <h2 id="edit-heading" className="text-lg font-semibold">
          Edit metadata
        </h2>
        <p className="text-sm text-muted-foreground">
          Changes are audited and applied by the worker. Leave a field as it is to keep its value.
          Edits to these fields: {EDITABLE_FIELDS.map((field) => field.label.toLowerCase()).join(", ")}.
        </p>
        <MetadataEditForm documentId={doc.id} current={currentFieldValues(doc)} />
      </section>
    </div>
  );
}
