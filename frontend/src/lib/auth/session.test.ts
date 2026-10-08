// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { describe, expect, it, vi } from "vitest";
import {
  clearSession,
  getAccessToken,
  hasSession,
  refreshSession,
  setAccessToken,
  setRefreshHandler,
  subscribeSession,
} from "./session";

const TOKEN = "tok-secret-123";

function storageDump(storage: Storage): string {
  return Object.keys(storage)
    .map((k) => `${k}=${storage.getItem(k) ?? ""}`)
    .join("\n");
}

describe("session", () => {
  it("keeps the token in memory only, never in localStorage or sessionStorage", async () => {
    setAccessToken(TOKEN);
    setRefreshHandler(() => Promise.resolve("tok-refreshed-456"));
    await refreshSession();
    expect(getAccessToken()).toBe("tok-refreshed-456");
    for (const store of [window.localStorage, window.sessionStorage]) {
      expect(storageDump(store)).not.toContain("tok-");
    }
  });

  it("sets, reports and clears the token and notifies subscribers", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeSession(listener);
    expect(hasSession()).toBe(false);
    setAccessToken(TOKEN);
    expect(hasSession()).toBe(true);
    clearSession();
    expect(getAccessToken()).toBeNull();
    expect(listener).toHaveBeenCalledTimes(2);
    unsubscribe();
    setAccessToken(TOKEN);
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("resolves null without a refresh handler", async () => {
    setRefreshHandler(null);
    expect(await refreshSession()).toBeNull();
  });

  it("shares one refresh request among concurrent callers", async () => {
    const handler = vi.fn(() => Promise.resolve("tok-new"));
    setRefreshHandler(handler);
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(results).toEqual(["tok-new", "tok-new", "tok-new"]);
    expect(handler).toHaveBeenCalledTimes(1);
  });

  it("clears the session when the refresh fails", async () => {
    setAccessToken(TOKEN);
    setRefreshHandler(() => Promise.reject(new Error("down")));
    expect(await refreshSession()).toBeNull();
    expect(hasSession()).toBe(false);
  });
});
