import type { SessionUser } from "@/lib/server/api";
import { Button } from "@/components/ui/button";
import { NavLink } from "@/components/console/nav-link";
import { logout } from "@/app/(console)/actions";

export const CONSOLE_NAV = [
  { href: "/search", label: "Search" },
  { href: "/queue", label: "Queue" },
  { href: "/dashboard", label: "Dashboard" },
  { href: "/baseline", label: "Baseline" },
  { href: "/documents", label: "Documents" },
  { href: "/ingest", label: "Ingest" },
];

interface ConsoleHeaderProps {
  user: SessionUser;
  showNav: boolean;
}

export function ConsoleHeader({ user, showNav }: ConsoleHeaderProps) {
  return (
    <header className="border-b bg-background">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-4 py-3 sm:px-6">
        <span className="text-lg font-semibold">TaxResearch Console</span>
        {showNav ? (
          <nav aria-label="Main">
            <ul className="flex flex-wrap gap-1">
              {CONSOLE_NAV.map((item) => (
                <li key={item.href}>
                  <NavLink href={item.href}>{item.label}</NavLink>
                </li>
              ))}
            </ul>
          </nav>
        ) : null}
        <div className="ml-auto flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{user.display_name}</span>
          <form action={logout}>
            <Button type="submit" variant="outline" size="sm">
              Log out
            </Button>
          </form>
        </div>
      </div>
    </header>
  );
}
