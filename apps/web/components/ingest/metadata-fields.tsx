import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** The optional identifying fields shared by the URL and the file forms. Blank ones are not sent. */
export function IdentifyingFields({ idPrefix }: { idPrefix: string }) {
  const field = (name: string, label: string, options: { placeholder?: string; type?: string } = {}) => {
    const id = `${idPrefix}-${name}`;
    return (
      <div className="space-y-2" key={name}>
        <Label htmlFor={id}>{label}</Label>
        <Input
          id={id}
          name={name}
          type={options.type ?? "text"}
          placeholder={options.placeholder}
          maxLength={300}
        />
      </div>
    );
  };

  return (
    <details className="rounded-md border p-4">
      <summary className="cursor-pointer text-sm font-medium">Identifying details (optional)</summary>
      <p className="mt-2 text-sm text-muted-foreground">
        Fill these in when the file does not carry its own identifiers. Blank fields are left out.
      </p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        {field("title", "Title", { placeholder: "Shown until the metadata is extracted" })}
        {field("series", "Series", { placeholder: "CT, IT, UT" })}
        {field("number", "Number", { placeholder: "11" })}
        {field("year", "Year", { placeholder: "2017" })}
        {field("circular_a", "Circular A", { placeholder: "First circular number" })}
        {field("circular_b", "Circular B", { placeholder: "Second circular number" })}
        {field("case_number", "Case number", { placeholder: "CA 1234/2020" })}
        {field("court_code", "Court code", { placeholder: "SC, HC-DEL" })}
        {field("decision_date", "Decision date", { type: "date" })}
      </div>
    </details>
  );
}
