// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowDownUp, Plus, Search, SlidersHorizontal } from "lucide-react";
import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { t } from "@/lib/i18n";
import { usePermission } from "@/lib/permissions";
import { AssetCard } from "../components/AssetCard";
import { AssetFilters } from "../components/AssetFilters";
import { AssetTable } from "../components/AssetTable";
import { ColumnChooser } from "../components/ColumnChooser";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "../components/control-class";
import { FilterChips } from "../components/FilterChips";
import { SavedViewMenu } from "../components/SavedViewMenu";
import { useAssetColumns } from "../hooks/useAssetColumns";
import { useAssets } from "../hooks/useAssets";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { COLUMN_IDS, type ColumnId } from "../lib/asset-columns";
import {
  clearFilters,
  DEFAULT_SORT,
  hasActiveFilters,
  isSortValid,
  parseListState,
  stateFromView,
  toSearchParams,
  type AssetFilters as Filters,
  type AssetListState,
} from "../lib/asset-filter-params";
import { SORT_OPTIONS } from "../lib/asset-options";
import type { SavedView } from "../types";

const SEARCH_DEBOUNCE_MS = 300;
const TABLE_QUERY = "(min-width: 1024px)";

/** Values seen so far in the results, kept across filters so a chosen option does not vanish with its rows. */
function useSeen(values: readonly string[]): string[] {
  const [seen, setSeen] = useState<string[]>([]);
  useEffect(() => {
    setSeen((prev) => {
      const next = new Set(prev);
      for (const value of values) next.add(value);
      return next.size === prev.length ? prev : [...next];
    });
  }, [values]);
  return seen;
}

/** Fetches the next page when the sentinel scrolls into view; the "Load more" button covers keyboards. */
function useSentinel(enabled: boolean, onVisible: () => void): React.RefObject<HTMLDivElement | null> {
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const node = ref.current;
    if (!enabled || node === null || typeof IntersectionObserver !== "function") return undefined;
    const observer = new IntersectionObserver((entries) => {
      if (entries.some((entry) => entry.isIntersecting)) onVisible();
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
    };
  }, [enabled, onVisible]);
  return ref;
}

export const AssetsPage: React.FC = () => {
  const navigate = useNavigate();
  const canCreate = usePermission("asset.create");
  const [searchParams, setSearchParams] = useSearchParams();
  const state: AssetListState = useMemo(() => parseListState(searchParams), [searchParams]);
  const { columns, setColumns } = useAssetColumns();
  const isTable = useMediaQuery(TABLE_QUERY);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const { query, items } = useAssets(state);

  const write = useCallback(
    (next: AssetListState, replace = false): void => {
      setSearchParams(toSearchParams(next), { replace });
    },
    [setSearchParams],
  );
  const setFilters = (filters: Filters, replace = false): void => {
    write({ ...state, filters }, replace);
  };

  // The search box: typing is debounced into the URL (replacing the entry, so Back skips keystrokes);
  // a URL change from outside (Back, a saved view) flows back into the box.
  const urlQ = state.filters.q;
  const [text, setText] = useState(urlQ);
  useEffect(() => {
    setText(urlQ);
  }, [urlQ]);
  useEffect(() => {
    if (text.trim() === urlQ) return undefined;
    const handle = setTimeout(() => {
      write({ ...state, filters: { ...state.filters, q: text } }, true);
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      clearTimeout(handle);
    };
  }, [text, urlQ, state, write]);

  const knownStatuses = useSeen(useMemo(() => items.map((item) => item.status), [items]));
  const knownCriticality = useSeen(
    useMemo(() => items.flatMap((item) => (item.criticality === null ? [] : [item.criticality])), [items]),
  );

  const { fetchNextPage, hasNextPage, isFetchingNextPage } = query;
  const loadMore = useCallback((): void => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  }, [fetchNextPage, hasNextPage, isFetchingNextPage]);
  const sentinel = useSentinel(hasNextPage && !query.isFetchNextPageError, loadMore);

  const applyView = (view: SavedView): void => {
    const next = stateFromView(view);
    const chosen = view.columns.filter((id): id is ColumnId =>
      (COLUMN_IDS as readonly string[]).includes(id),
    );
    if (chosen.length > 0) setColumns(chosen);
    write(next);
  };

  const filterCount = hasActiveFilters(state.filters);
  const sortApplies = state.filters.q === "";
  const descending = state.sort.startsWith("-");
  const sortKey = state.sort.replace(/^-/, "");

  const renderResults = (): React.ReactNode => {
    if (query.isPending) return <Skeleton rows={6} />;
    if (query.isError && query.data === undefined) {
      return (
        <ErrorState
          message={t("assets.list.load_failed")}
          onRetry={() => {
            void query.refetch();
          }}
        />
      );
    }
    if (items.length === 0) {
      if (filterCount || state.filters.q !== "") {
        return (
          <EmptyState
            title={t("assets.list.no_match_title")}
            message={t("assets.list.no_match_body")}
            action={{
              label: t("assets.list.clear_filters"),
              onClick: () => {
                setText("");
                setFilters(clearFilters(state.filters, false));
              },
            }}
          />
        );
      }
      return (
        <EmptyState
          title={t("assets.list.empty_title")}
          message={t("assets.list.empty_body")}
          {...(canCreate
            ? {
                action: {
                  label: t("assets.list.new_asset"),
                  onClick: () => {
                    void navigate("/assets/new");
                  },
                },
              }
            : {})}
        />
      );
    }
    return (
      <div className="space-y-4">
        {isTable ? (
          <AssetTable
            items={items}
            columns={columns}
            sort={state.sort}
            sortApplies={sortApplies}
            onSort={(sort) => {
              write({ ...state, sort });
            }}
          />
        ) : (
          <ul aria-label={t("assets.list.cards_label")} className="space-y-3">
            {items.map((item) => (
              <AssetCard key={item.id} item={item} />
            ))}
          </ul>
        )}
        {query.isFetchNextPageError && (
          <p role="alert" className="text-sm text-danger">
            {t("assets.list.load_more_failed")}
          </p>
        )}
        {hasNextPage && (
          <div ref={sentinel} className="flex justify-center">
            <button type="button" disabled={isFetchingNextPage} onClick={loadMore} className={BUTTON_CLASS}>
              {isFetchingNextPage ? t("ui.state.loading") : t("assets.list.load_more")}
            </button>
          </div>
        )}
        <p role="status" className="text-center text-xs text-muted">
          {hasNextPage
            ? t("assets.list.showing_some", { count: items.length })
            : t("assets.list.showing_all", { count: items.length })}
        </p>
      </div>
    );
  };

  return (
    <section className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-bold tracking-tight">{t("assets.list.title")}</h1>
        {canCreate && (
          <button
            type="button"
            onClick={() => {
              void navigate("/assets/new");
            }}
            className={PRIMARY_BUTTON_CLASS}
          >
            <Plus aria-hidden="true" className="h-4 w-4" />
            {t("assets.list.new_asset")}
          </button>
        )}
      </div>

      <div className="sticky top-0 z-10 -mx-4 bg-background px-4 py-2 md:-mx-6 md:px-6 lg:static lg:z-auto lg:mx-0 lg:p-0">
        <form
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
          }}
          className="relative"
        >
          <Search
            aria-hidden="true"
            className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted"
          />
          <label htmlFor="asset-search" className="sr-only">
            {t("assets.list.search_label")}
          </label>
          <input
            id="asset-search"
            type="search"
            value={text}
            placeholder={t("assets.list.search_placeholder")}
            onChange={(event) => {
              setText(event.target.value);
            }}
            className={`${CONTROL_CLASS} pl-9`}
          />
        </form>
      </div>

      <div className="flex flex-wrap items-start gap-2">
        <button
          type="button"
          aria-expanded={filtersOpen}
          aria-controls="asset-filters-panel"
          onClick={() => {
            setFiltersOpen(!filtersOpen);
          }}
          className={BUTTON_CLASS}
        >
          <SlidersHorizontal aria-hidden="true" className="h-4 w-4" />
          {t("assets.filters.toggle")}
        </button>
        <SavedViewMenu state={state} columns={columns} onApply={applyView} />
        {isTable ? (
          <ColumnChooser columns={columns} onChange={setColumns} />
        ) : (
          <div className="flex items-center gap-2">
            <label htmlFor="asset-sort" className="sr-only">
              {t("assets.sort.label")}
            </label>
            <select
              id="asset-sort"
              value={isSortValid(state.sort) ? sortKey : DEFAULT_SORT.slice(1)}
              onChange={(event) => {
                write({ ...state, sort: descending ? `-${event.target.value}` : event.target.value });
              }}
              className={`${CONTROL_CLASS} w-auto`}
            >
              {SORT_OPTIONS.map((option) => (
                <option key={option.key} value={option.key}>
                  {t(option.labelKey)}
                </option>
              ))}
            </select>
            <button
              type="button"
              aria-pressed={descending}
              onClick={() => {
                write({ ...state, sort: descending ? sortKey : `-${sortKey}` });
              }}
              className={BUTTON_CLASS}
            >
              <ArrowDownUp aria-hidden="true" className="h-4 w-4" />
              {descending ? t("assets.sort.descending") : t("assets.sort.ascending")}
            </button>
          </div>
        )}
      </div>

      {filtersOpen && (
        <div id="asset-filters-panel" className="rounded-xl border border-border bg-surface p-4">
          <AssetFilters
            filters={state.filters}
            onChange={setFilters}
            knownStatuses={knownStatuses}
            knownCriticality={knownCriticality}
          />
        </div>
      )}

      <FilterChips filters={state.filters} onChange={setFilters} />
      {!sortApplies && <p className="text-xs text-muted">{t("assets.sort.relevance_note")}</p>}

      {renderResults()}
    </section>
  );
};
