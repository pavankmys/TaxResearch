/** A block's position in PDF points, from the top-left of the page (pdfplumber's convention). */
export interface Bbox {
  x0: number;
  top: number;
  x1: number;
  bottom: number;
}

export interface PageSize {
  widthPt: number;
  heightPt: number;
}

export interface PercentBox {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Page images are rendered at this resolution by the API (plan decision 7). */
export const RENDER_DPI = 110;
const POINTS_PER_INCH = 72;

/** The bbox if it holds four finite numbers forming a box with positive size, else null. */
export function parseBbox(value: unknown): Bbox | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return null;
  }
  const record = value as Record<string, unknown>;
  const { x0, top, x1, bottom } = record;
  if (
    typeof x0 !== "number" ||
    typeof top !== "number" ||
    typeof x1 !== "number" ||
    typeof bottom !== "number" ||
    ![x0, top, x1, bottom].every(Number.isFinite) ||
    x1 <= x0 ||
    bottom <= top
  ) {
    return null;
  }
  return { x0, top, x1, bottom };
}

/** Page size in points for a page image rendered at `dpi` (pixels to points). */
export function pageSizeFromPixels(
  pixels: { width: number; height: number },
  dpi: number = RENDER_DPI,
): PageSize {
  const scale = POINTS_PER_INCH / dpi;
  return { widthPt: pixels.width * scale, heightPt: pixels.height * scale };
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(high, Math.max(low, value));
}

/** The bbox as percentages of the page size, clipped to the page. */
export function bboxToPercent(bbox: Bbox, page: PageSize): PercentBox {
  const left = clamp((bbox.x0 / page.widthPt) * 100, 0, 100);
  const top = clamp((bbox.top / page.heightPt) * 100, 0, 100);
  const width = clamp(((bbox.x1 - bbox.x0) / page.widthPt) * 100, 0, 100 - left);
  const height = clamp(((bbox.bottom - bbox.top) / page.heightPt) * 100, 0, 100 - top);
  return { left, top, width, height };
}
