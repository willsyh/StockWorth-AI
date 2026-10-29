import { FilePlus2, History, LayoutDashboard, LineChart, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/saham", label: "Analisis Saham", icon: LineChart },
  { to: "/analisis/baru", label: "Analisis Baru", icon: FilePlus2 },
  { to: "/riwayat", label: "Riwayat Analisis", icon: History },
  { to: "/pengaturan", label: "Pengaturan", icon: Settings },
];

export function titleForPath(pathname: string): { title: string; parent?: { label: string; to: string } } {
  if (pathname === "/") return { title: "Dashboard" };
  if (pathname === "/analisis/baru") return { title: "Analisis Baru" };
  if (pathname.startsWith("/analisis/")) return { title: "Laporan Analisis", parent: { label: "Riwayat Analisis", to: "/riwayat" } };
  if (pathname === "/saham") return { title: "Analisis Saham" };
  if (pathname.startsWith("/saham/")) return { title: pathname.split("/")[2]?.toUpperCase() ?? "Saham", parent: { label: "Analisis Saham", to: "/saham" } };
  if (pathname === "/riwayat") return { title: "Riwayat Analisis" };
  if (pathname === "/pengaturan") return { title: "Pengaturan" };
  return { title: "StockWorth AI" };
}
