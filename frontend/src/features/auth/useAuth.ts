// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { useCallback, useSyncExternalStore } from "react";
import {
  clearSession,
  getAccessToken,
  hasSession,
  setAccessToken,
  setRefreshHandler,
  subscribeSession,
} from "@/lib/auth";
import { exchangeSession, logoutSession, refreshSessionToken } from "./api";

// Wire the refresh handler so single-flight refresh calls the BFF endpoint
setRefreshHandler(async () => {
  try {
    const res = await refreshSessionToken();
    return res.access_token;
  } catch {
    return null;
  }
});

export function useAuth() {
  const signedIn = useSyncExternalStore(subscribeSession, hasSession);
  const token = useSyncExternalStore(subscribeSession, getAccessToken);

  const login = useCallback(async (code: string, redirectUri: string, codeVerifier?: string) => {
    const res = await exchangeSession(code, redirectUri, codeVerifier);
    setAccessToken(res.access_token);
    return res;
  }, []);

  const logout = useCallback(async () => {
    try {
      await logoutSession();
    } finally {
      clearSession();
    }
  }, []);

  return {
    signedIn,
    token,
    login,
    logout,
  };
}
