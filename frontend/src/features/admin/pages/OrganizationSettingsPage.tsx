// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useEffect, useState } from "react";
import { ErrorState, Skeleton } from "@/components/ui";
import { can, useMe } from "@/lib/permissions";

interface OrgSettings {
  provisioning?: string;
  locale?: string;
  timezone?: string;
  currency?: string;
}

export const OrganizationSettingsPage: React.FC = () => {
  const { data: me } = useMe();
  const canManage = can(me, "organization.settings_manage") || can(me, "organization.manage");
  const [settings, setSettings] = useState<OrgSettings>({
    provisioning: "invite_only",
    locale: "en",
    timezone: "UTC",
    currency: "USD",
  });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/organizations/settings")
      .then((res) => {
        if (!res.ok) throw new Error("Failed to load settings");
        return res.json() as Promise<{ data?: OrgSettings }>;
      })
      .then((body) => {
        if (body.data) setSettings(body.data);
      })
      .catch(() => {})
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const handleSubmit = async (e: React.SyntheticEvent) => {
    e.preventDefault();
    if (!canManage) return;
    setSaving(true);
    setSaved(false);
    setError(null);
    try {
      const res = await fetch("/api/v1/organizations/settings", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      if (!res.ok) throw new Error("Failed to update organization settings");
      setSaved(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Skeleton rows={4} />;

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="border-b border-border pb-5">
        <h1 className="text-2xl font-bold tracking-tight">{"Organization Settings"}</h1>
        <p className="text-sm text-muted">{"Manage global policies, localization, and defaults"}</p>
      </div>

      {error && <ErrorState message={error} />}
      {saved && (
        <div className="rounded-lg border border-success bg-success-surface p-3 text-sm text-success">
          {"Organization settings saved successfully."}
        </div>
      )}

      <form
        onSubmit={(e) => {
          void handleSubmit(e);
        }}
        className="space-y-6 rounded-xl border border-border bg-surface p-6 shadow-sm"
      >
        <div className="space-y-2">
          <label htmlFor="setting-provisioning" className="block text-sm font-medium text-foreground">
            {"Sign-in Provisioning Policy"}
          </label>
          <select
            id="setting-provisioning"
            disabled={!canManage}
            value={settings.provisioning ?? "invite_only"}
            onChange={(e) => {
              setSettings((prev) => ({ ...prev, provisioning: e.target.value }));
            }}
            className="flex h-11 w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus disabled:opacity-60"
          >
            <option value="invite_only">{"Invite Only (Members must be pre-created)"}</option>
            <option value="require_role">{"Require IdP Role"}</option>
            <option value="open">{"Open (Auto-provision upon first sign-in)"}</option>
          </select>
        </div>

        <div className="space-y-2">
          <label htmlFor="setting-timezone" className="block text-sm font-medium text-foreground">
            {"Default Timezone"}
          </label>
          <select
            id="setting-timezone"
            disabled={!canManage}
            value={settings.timezone ?? "UTC"}
            onChange={(e) => {
              setSettings((prev) => ({ ...prev, timezone: e.target.value }));
            }}
            className="flex h-11 w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus disabled:opacity-60"
          >
            <option value="UTC">{"UTC (Coordinated Universal Time)"}</option>
            <option value="Asia/Kolkata">{"Asia/Kolkata (IST)"}</option>
            <option value="America/New_York">{"America/New_York (EST/EDT)"}</option>
            <option value="Europe/London">{"Europe/London (GMT/BST)"}</option>
          </select>
        </div>

        <div className="space-y-2">
          <label htmlFor="setting-locale" className="block text-sm font-medium text-foreground">
            {"Default Locale"}
          </label>
          <select
            id="setting-locale"
            disabled={!canManage}
            value={settings.locale ?? "en"}
            onChange={(e) => {
              setSettings((prev) => ({ ...prev, locale: e.target.value }));
            }}
            className="flex h-11 w-full rounded-lg border border-border bg-surface px-3 text-sm text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus disabled:opacity-60"
          >
            <option value="en">{"English (en)"}</option>
            <option value="en-IN">{"English — India (en-IN)"}</option>
            <option value="en-US">{"English — United States (en-US)"}</option>
          </select>
        </div>

        {canManage && (
          <div className="pt-2">
            <button
              type="submit"
              disabled={saving}
              className="inline-flex min-h-11 items-center justify-center rounded-lg bg-primary px-5 py-2.5 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90 disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
            >
              {saving ? "Saving…" : "Save Settings"}
            </button>
          </div>
        )}
      </form>
    </div>
  );
};
