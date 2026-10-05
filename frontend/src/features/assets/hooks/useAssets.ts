// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useInfiniteQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { assetKeys, fetchAssetPage } from "../api/assets";
import { toApiParams, type AssetListState } from "../lib/asset-filter-params";

/** The asset list as an infinite query over `next_cursor`; a new filter or sort starts again at page one. */
export function useAssets(state: AssetListState) {
  const key = toApiParams(state).toString();
  const query = useInfiniteQuery({
    queryKey: assetKeys.list(key),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam, signal }) => {
      const after = pageParam;
      return fetchAssetPage(toApiParams(state, { after }).toString(), signal);
    },
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
  const items = useMemo(() => query.data?.pages.flatMap((page) => page.items) ?? [], [query.data]);
  return { query, items };
}
