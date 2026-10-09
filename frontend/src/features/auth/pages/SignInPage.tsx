// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { Activity, LogIn, Shield } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router";
import { HealthStatus } from "@/app/HealthStatus";
import { Skeleton } from "@/components/ui";
import { beginLoginTransaction } from "@/lib/auth";
import { t } from "@/lib/i18n";
import { fetchPublicConfig } from "../api";
import type { PublicConfig } from "../types";
import { useAuth } from "../useAuth";

export const SignInPage: React.FC = () => {
  const { signedIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (signedIn) {
      const from = (location.state as { from?: string } | null)?.from ?? "/";
      void navigate(from, { replace: true });
    }
  }, [signedIn, navigate, location]);

  useEffect(() => {
    fetchPublicConfig()
      .then((cfg) => {
        setConfig(cfg);
      })
      .catch(() => {})
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const handleSignIn = () => {
    if (!config) return;
    void beginLoginTransaction().then((pkce) => {
      const redirectUri = window.location.origin + "/auth/callback";
      const pkceQuery =
        `&code_challenge=${encodeURIComponent(pkce.codeChallenge)}` +
        `&code_challenge_method=${pkce.codeChallengeMethod}` +
        `&state=${encodeURIComponent(pkce.state)}&nonce=${encodeURIComponent(pkce.nonce)}`;
      if (config.auth_mode === "mock") {
        window.location.href = `/api/auth/mock/authorize?redirect_uri=${encodeURIComponent(redirectUri)}${pkceQuery}`;
      } else {
        window.location.href =
          `${config.authority}/oauth/v2/authorize?client_id=${encodeURIComponent(config.client_id)}` +
          `&response_type=code&scope=${encodeURIComponent(config.scopes.join(" "))}` +
          `&redirect_uri=${encodeURIComponent(redirectUri)}${pkceQuery}`;
      }
    });
  };

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-background px-4 py-8 text-foreground sm:px-6 lg:px-8">
      <div className="w-full max-w-md space-y-8 rounded-2xl border border-border bg-surface p-8 shadow-xl">
        <div className="flex flex-col items-center text-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
            <Activity className="h-8 w-8" aria-hidden="true" />
          </div>
          <h1 className="mt-4 text-2xl font-bold tracking-tight">{t("pages.sign_in.title")}</h1>
          <p className="mt-2 text-sm text-muted">{t("pages.sign_in.description")}</p>
        </div>

        {loading ? (
          <Skeleton rows={2} />
        ) : (
          <div className="space-y-4">
            <button
              type="button"
              onClick={handleSignIn}
              className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              {config?.auth_mode === "mock" ? (
                <>
                  <Shield className="h-4 w-4" aria-hidden="true" />
                  <span>{t("pages.sign_in.mock_button")}</span>
                </>
              ) : (
                <>
                  <LogIn className="h-4 w-4" aria-hidden="true" />
                  <span>{t("pages.sign_in.button")}</span>
                </>
              )}
            </button>
          </div>
        )}

        <div className="border-t border-border pt-6">
          <HealthStatus />
        </div>
      </div>
    </div>
  );
};
