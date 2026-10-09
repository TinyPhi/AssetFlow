// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ErrorState, Skeleton } from "@/components/ui";
import { completeLoginTransaction } from "@/lib/auth";
import { useAuth } from "../useAuth";

export const AuthCallbackPage: React.FC = () => {
  const [searchParams] = useSearchParams();
  const { login } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  const code = searchParams.get("code");
  const state = searchParams.get("state");

  useEffect(() => {
    if (!code) {
      setError("No authorization code provided.");
      return;
    }

    const redirectUri = window.location.origin + "/auth/callback";
    let txn;
    try {
      txn = completeLoginTransaction(state);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed");
      return;
    }
    login(code, redirectUri, txn)
      .then(() => {
        void navigate("/", { replace: true });
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Authentication failed");
      });
  }, [code, state, login, navigate]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center p-4">
        <ErrorState
          message={error}
          onRetry={() => {
            void navigate("/sign-in", { replace: true });
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <div className="w-full max-w-sm space-y-4">
        <Skeleton rows={3} />
      </div>
    </div>
  );
};
