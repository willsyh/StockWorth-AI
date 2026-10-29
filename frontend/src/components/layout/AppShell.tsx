import { useEffect, useState, type FormEvent } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  ChevronRight,
  LogOut,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Search,
  Sun,
  User as UserIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Dialog, DialogDescription, DialogTitle, SheetContent } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useTheme, type ThemePreference } from "@/app/theme";
import { useAuth } from "@/app/auth";
import { useHealth } from "@/hooks/queries";
import { cn } from "@/lib/utils";
import { NAV_ITEMS, titleForPath } from "./nav";

const COLLAPSE_KEY = "stockworth-sidebar-collapsed";

function Brand({ collapsed }: { collapsed?: boolean }) {
  return (
    <Link to="/" className="flex items-center gap-2.5 rounded-md px-1 py-1" aria-label="StockWorth AI, ke Dashboard">
      <img src="/logo-mark.png" alt="" width={32} height={32} className="size-8 shrink-0" />
      {!collapsed && (
        <span className="text-[15px] font-semibold tracking-tight">
          StockWorth <span className="text-primary">AI</span>
        </span>
      )}
    </Link>
  );
}

function NavLinks({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  return (
    <nav aria-label="Navigasi utama" className="flex flex-col gap-0.5">
      {NAV_ITEMS.map((item) => {
        const link = (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cn(
                "flex h-9 items-center gap-3 rounded-md px-2.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                isActive && "bg-accent text-accent-foreground hover:bg-accent hover:text-accent-foreground",
                collapsed && "justify-center px-0",
              )
            }
          >
            <item.icon className="size-[18px] shrink-0" aria-hidden="true" />
            {collapsed ? <span className="sr-only">{item.label}</span> : item.label}
          </NavLink>
        );
        return collapsed ? (
          <Tooltip key={item.to}>
            <TooltipTrigger asChild>{link}</TooltipTrigger>
            <TooltipContent side="right">{item.label}</TooltipContent>
          </Tooltip>
        ) : (
          link
        );
      })}
    </nav>
  );
}

function StatusFooter({ collapsed }: { collapsed?: boolean }) {
  const health = useHealth();
  const offline = health.isError;
  const local = health.data?.storage === "local";
  const label = offline ? "Server tidak terhubung" : local ? "Mode lokal" : health.data ? "Tersambung" : "Memeriksa…";
  const color = offline ? "bg-negative" : local ? "bg-warning" : health.data ? "bg-positive" : "bg-muted-foreground";
  return (
    <div className={cn("flex items-center gap-2 px-2.5 text-xs text-muted-foreground", collapsed && "justify-center px-0")} role="status">
      <span className={cn("size-2 shrink-0 rounded-full", color)} aria-hidden="true" />
      {collapsed ? <span className="sr-only">{label}</span> : label}
    </div>
  );
}

function ThemeToggle() {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const options: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
    { value: "light", label: "Terang", icon: Sun },
    { value: "dark", label: "Gelap", icon: Moon },
    { value: "system", label: "Ikuti sistem", icon: Monitor },
  ];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Ganti tema">
          {resolvedTheme === "dark" ? <Moon /> : <Sun />}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {options.map((o) => (
          <DropdownMenuItem key={o.value} onSelect={() => setTheme(o.value)} aria-checked={theme === o.value} role="menuitemradio">
            <o.icon />
            {o.label}
            {theme === o.value && <span className="ml-auto text-xs text-primary">Aktif</span>}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function UserMenu() {
  const auth = useAuth();
  const navigate = useNavigate();
  if (!auth.enabled || !auth.user) return null;
  const email = auth.user.email ?? "Pengguna";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Menu profil">
          <span className="flex size-7 items-center justify-center rounded-full bg-accent text-xs font-semibold uppercase text-accent-foreground">
            {email.slice(0, 1)}
          </span>
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="truncate">{email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => navigate("/pengaturan")}>
          <UserIcon /> Profil & pengaturan
        </DropdownMenuItem>
        <DropdownMenuItem
          onSelect={async () => {
            await auth.signOut();
            navigate("/masuk");
          }}
        >
          <LogOut /> Keluar
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function HeaderSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    const v = q.trim();
    if (!v) return;
    navigate(`/riwayat?q=${encodeURIComponent(v)}`);
    setQ("");
  };
  return (
    <form onSubmit={submit} role="search" className="relative hidden w-64 md:block">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
      <Input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Cari kode atau nama emiten"
        aria-label="Cari analisis berdasarkan kode atau nama emiten"
        className="h-8 pl-8"
      />
    </form>
  );
}

export function AppShell() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === "1";
    } catch {
      return false;
    }
  });
  const [mobileOpen, setMobileOpen] = useState(false);
  const { title, parent } = titleForPath(location.pathname);

  useEffect(() => {
    try {
      localStorage.setItem(COLLAPSE_KEY, collapsed ? "1" : "0");
    } catch {
      /* ignore */
    }
  }, [collapsed]);

  useEffect(() => {
    document.title = `${title} · StockWorth AI`;
  }, [title]);

  return (
    <div className="flex min-h-screen">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-card focus:px-3 focus:py-2 focus:shadow"
      >
        Lewati ke konten
      </a>

      {/* Desktop sidebar */}
      <aside
        className={cn(
          "sticky top-0 hidden h-screen shrink-0 flex-col border-r bg-card transition-[width] duration-200 lg:flex",
          collapsed ? "w-[68px]" : "w-60",
        )}
      >
        <div className={cn("flex h-14 items-center px-4", collapsed && "justify-center px-0")}>
          <Brand collapsed={collapsed} />
        </div>
        <div className={cn("flex-1 overflow-y-auto px-3 py-3", collapsed && "px-2")}>
          <NavLinks collapsed={collapsed} />
        </div>
        <div className={cn("flex flex-col gap-3 border-t px-3 py-3", collapsed && "items-center px-2")}>
          <StatusFooter collapsed={collapsed} />
          <Button
            variant="ghost"
            size={collapsed ? "icon" : "sm"}
            className={cn(!collapsed && "justify-start text-muted-foreground")}
            onClick={() => setCollapsed((c) => !c)}
            aria-label={collapsed ? "Perluas sidebar" : "Ciutkan sidebar"}
            aria-expanded={!collapsed}
          >
            {collapsed ? <PanelLeftOpen /> : <PanelLeftClose />}
            {!collapsed && "Ciutkan"}
          </Button>
        </div>
      </aside>

      {/* Mobile sidebar */}
      <Dialog open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent>
          <DialogTitle className="sr-only">Navigasi</DialogTitle>
          <DialogDescription className="sr-only">Menu navigasi utama</DialogDescription>
          <div className="flex h-14 items-center px-4">
            <Brand />
          </div>
          <div className="flex-1 px-3 py-3">
            <NavLinks onNavigate={() => setMobileOpen(false)} />
          </div>
          <div className="border-t px-3 py-3">
            <StatusFooter />
          </div>
        </SheetContent>
      </Dialog>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/90 px-4 backdrop-blur supports-[backdrop-filter]:bg-background/75 sm:px-6">
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Buka menu">
            <Menu />
          </Button>
          <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-1.5 text-sm">
            {parent && (
              <>
                <Link to={parent.to} className="hidden truncate text-muted-foreground hover:text-foreground sm:inline">
                  {parent.label}
                </Link>
                <ChevronRight className="hidden size-3.5 text-muted-foreground sm:inline" aria-hidden="true" />
              </>
            )}
            <span className="truncate font-medium" aria-current="page">
              {title}
            </span>
          </nav>
          <div className="ml-auto flex items-center gap-1.5">
            <HeaderSearch />
            <ThemeToggle />
            <UserMenu />
          </div>
        </header>
        <main id="main" className="mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 sm:px-6 lg:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
