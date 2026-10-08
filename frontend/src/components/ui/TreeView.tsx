// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ChevronDown, ChevronRight, Folder, MoreVertical } from "lucide-react";
import type React from "react";
import { useState } from "react";

export interface TreeNode {
  id: string;
  name: string;
  count?: number | undefined;
  parentId?: string | null | undefined;
  children?: TreeNode[] | undefined;
}

interface TreeViewProps {
  nodes: TreeNode[];
  selectedId?: string | undefined;
  onSelect?: ((node: TreeNode) => void) | undefined;
  onAddChild?: ((node: TreeNode) => void) | undefined;
  onRename?: ((node: TreeNode) => void) | undefined;
  onMove?: ((node: TreeNode) => void) | undefined;
  onArchive?: ((node: TreeNode) => void) | undefined;
  canManage?: boolean | undefined;
}

const TreeNodeItem: React.FC<{
  node: TreeNode;
  level: number;
  selectedId?: string | undefined;
  onSelect?: ((node: TreeNode) => void) | undefined;
  onAddChild?: ((node: TreeNode) => void) | undefined;
  onRename?: ((node: TreeNode) => void) | undefined;
  onMove?: ((node: TreeNode) => void) | undefined;
  onArchive?: ((node: TreeNode) => void) | undefined;
  canManage?: boolean | undefined;
}> = ({
  node,
  level,
  selectedId,
  onSelect,
  onAddChild,
  onRename,
  onMove,
  onArchive,
  canManage,
}) => {
  const [expanded, setExpanded] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const hasChildren = Boolean(node.children && node.children.length > 0);
  const isSelected = selectedId === node.id;

  return (
    <div role="treeitem" aria-expanded={hasChildren ? expanded : undefined} aria-selected={isSelected}>
      <div
        style={{ paddingLeft: `${String(Math.max(level * 16, 8))}px` }}
        className={`flex min-h-11 items-center justify-between rounded-lg px-2 py-1.5 transition-colors ${
          isSelected ? "bg-primary/15 text-primary font-medium" : "hover:bg-border/50 text-foreground"
        }`}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2">
          {hasChildren ? (
            <button
              type="button"
              onClick={() => {
                setExpanded(!expanded);
              }}
              className="flex h-7 w-7 items-center justify-center rounded hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
              aria-label={expanded ? "Collapse" : "Expand"}
            >
              {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
            </button>
          ) : (
            <span className="w-7" />
          )}

          <Folder className="h-4 w-4 shrink-0 text-muted" aria-hidden="true" />

          <button
            type="button"
            onClick={() => {
              onSelect?.(node);
            }}
            className="min-w-0 truncate text-left text-sm focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
          >
            {node.name}
          </button>

          {typeof node.count === "number" && (
            <span className="ml-2 rounded-full bg-border px-2 py-0.5 text-xs text-muted">
              {node.count}
            </span>
          )}
        </div>

        {canManage && (
          <div className="relative">
            <button
              type="button"
              onClick={() => {
                setMenuOpen(!menuOpen);
              }}
              aria-label="Actions"
              className="flex h-8 w-8 items-center justify-center rounded hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              <MoreVertical className="h-4 w-4 text-muted" />
            </button>

            {menuOpen && (
              <div
                role="menu"
                tabIndex={-1}
                className="absolute right-0 top-full z-10 mt-1 w-36 rounded-lg border border-border bg-surface py-1 shadow-lg"
              >
                {onAddChild && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      onAddChild(node);
                    }}
                    className="flex w-full px-3 py-1.5 text-left text-xs hover:bg-border"
                  >
                    {"Add child"}
                  </button>
                )}
                {onRename && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      onRename(node);
                    }}
                    className="flex w-full px-3 py-1.5 text-left text-xs hover:bg-border"
                  >
                    {"Rename"}
                  </button>
                )}
                {onMove && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      onMove(node);
                    }}
                    className="flex w-full px-3 py-1.5 text-left text-xs hover:bg-border"
                  >
                    {"Move to…"}
                  </button>
                )}
                {onArchive && (
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => {
                      setMenuOpen(false);
                      onArchive(node);
                    }}
                    className="flex w-full px-3 py-1.5 text-left text-xs text-danger hover:bg-danger/10"
                  >
                    {"Archive"}
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      {hasChildren && expanded && (
        <div role="group" className="space-y-1">
          {node.children?.map((child) => (
            <TreeNodeItem
              key={child.id}
              node={child}
              level={level + 1}
              selectedId={selectedId}
              onSelect={onSelect}
              onAddChild={onAddChild}
              onRename={onRename}
              onMove={onMove}
              onArchive={onArchive}
              canManage={canManage}
            />
          ))}
        </div>
      )}
    </div>
  );
};

export const TreeView: React.FC<TreeViewProps> = ({
  nodes,
  selectedId,
  onSelect,
  onAddChild,
  onRename,
  onMove,
  onArchive,
  canManage = true,
}) => (
  <nav aria-label="Hierarchy tree">
    <div role="tree" className="space-y-1">
      {nodes.map((node) => (
        <TreeNodeItem
          key={node.id}
          node={node}
          level={0}
          selectedId={selectedId}
          onSelect={onSelect}
          onAddChild={onAddChild}
          onRename={onRename}
          onMove={onMove}
          onArchive={onArchive}
          canManage={canManage}
        />
      ))}
    </div>
  </nav>
);
