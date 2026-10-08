// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

export interface PublicConfig {
  authority: string;
  client_id: string;
  redirect_uri: string;
  scopes: string[];
  auth_mode: "oidc" | "mock";
  idle_timeout_minutes: number;
  features: string[];
}

export interface SessionResponse {
  access_token: string;
  expires_in: number;
}
