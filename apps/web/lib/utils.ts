import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Join class names and resolve Tailwind conflicts (later classes win). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
