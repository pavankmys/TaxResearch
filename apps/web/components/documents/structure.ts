/**
 * Outline depth of a block from its structure_path. Each dot adds one level, so "p3" is level 0,
 * "p3.i2" is level 1 and "sched1.row12.c" is level 2. A block without a path sits at level 0.
 */
export function structureDepth(path: string | null | undefined): number {
  if (!path) {
    return 0;
  }
  return path.split(".").length - 1;
}
