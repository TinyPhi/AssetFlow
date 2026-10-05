// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type { HierarchyNode } from "../types";

/** The nodes in tree order (by path), each with its depth, for an indented option list. */
export function treeOrder(nodes: readonly HierarchyNode[]): { node: HierarchyNode; depth: number }[] {
  return [...nodes]
    .sort((a, b) => a.path.localeCompare(b.path))
    .map((node) => ({ node, depth: node.path === "" ? 0 : node.path.split(".").length - 1 }));
}

/** The name of the node with this id, or the id itself while the lookup has not loaded. */
export function nodeName(nodes: readonly HierarchyNode[] | undefined, id: string): string {
  return nodes?.find((node) => node.id === id)?.name ?? id;
}
