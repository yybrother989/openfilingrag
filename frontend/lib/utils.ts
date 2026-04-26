import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatScore(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return "—";
  return n.toFixed(digits);
}

export function shortText(s: string | null | undefined, max = 280): string {
  if (!s) return "";
  return s.length > max ? s.slice(0, max).trimEnd() + "…" : s;
}
