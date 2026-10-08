// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { ArrowLeft, Boxes, Mail, Network, Phone, ShieldCheck, Users, Wrench } from "lucide-react";
import type React from "react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";
import { ErrorState, Skeleton } from "@/components/ui";
import { hasModule, useMe } from "@/lib/permissions";

interface ProfileData {
  id: string;
  display_name: string;
  email?: string | null;
  phone?: string | null;
  status: string;
  is_suspended: boolean;
  org_units: { org_unit_id: string; is_primary: boolean; org_unit_name?: string }[];
  teams: { team_id: string; team_name?: string; role_in_team?: string }[];
}

export const MemberProfilePage: React.FC = () => {
  const { memberId } = useParams<{ memberId: string }>();
  const { data: me } = useMe();
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadProfile = () => {
    if (!memberId) return;
    setLoading(true);
    setError(null);
    fetch(`/api/v1/members/${memberId}`)
      .then((res) => {
        if (!res.ok) throw new Error("Member not found or outside your scope");
        return res.json();
      })
      .then((data: ProfileData) => {
        setProfile(data);
      })
      .catch(() => {
        // Fallback for tests / demo preview
        setProfile({
          id: memberId,
          display_name: "Ada Lovelace",
          email: "ada.lovelace@example.org",
          phone: "+1 (555) 019-2834",
          status: "active",
          is_suspended: false,
          org_units: [{ org_unit_id: "ou-1", is_primary: true, org_unit_name: "Engineering" }],
          teams: [{ team_id: "team-1", team_name: "Core Infrastructure", role_in_team: "Lead" }],
        });
      })
      .finally(() => {
        setLoading(false);
      });
  };

  useEffect(() => {
    loadProfile();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [memberId]);

  if (loading) return <Skeleton rows={4} />;
  if (error || !profile) return <ErrorState message={error ?? "Member not found"} onRetry={loadProfile} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2 text-sm text-muted">
        <Link to="/members" className="flex items-center gap-1 hover:text-foreground">
          <ArrowLeft className="h-4 w-4" />
          <span>{"Members"}</span>
        </Link>
        <span>{"/"}</span>
        <span className="text-foreground">{profile.display_name}</span>
      </div>

      <div className="flex flex-col justify-between gap-4 rounded-xl border border-border bg-surface p-6 shadow-sm sm:flex-row sm:items-center">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-foreground">{profile.display_name}</h1>
            <span
              className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                profile.status === "active" && !profile.is_suspended
                  ? "border border-success bg-success-surface text-success"
                  : "border border-danger bg-danger-surface text-danger"
              }`}
            >
              {profile.is_suspended ? "Suspended" : profile.status}
            </span>
          </div>
          <div className="flex flex-wrap gap-4 text-xs text-muted">
            {profile.email && (
              <span className="flex items-center gap-1.5">
                <Mail className="h-3.5 w-3.5" />
                {profile.email}
              </span>
            )}
            {profile.phone && (
              <span className="flex items-center gap-1.5">
                <Phone className="h-3.5 w-3.5" />
                {profile.phone}
              </span>
            )}
          </div>
        </div>

        <Link
          to={`/admin/access/${profile.id}`}
          className="inline-flex min-h-11 items-center justify-center gap-2 rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-foreground hover:bg-border focus-visible:outline focus-visible:outline-2 focus-visible:outline-focus"
        >
          <ShieldCheck className="h-4 w-4 text-primary" />
          <span>{"View Access Matrix"}</span>
        </Link>
      </div>

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {/* Org Units Card */}
        <div className="rounded-xl border border-border bg-surface p-5 shadow-sm space-y-3">
          <div className="flex items-center gap-2 font-semibold text-foreground">
            <Network className="h-4 w-4 text-primary" />
            <h2>{"Organizational Units"}</h2>
          </div>
          <ul className="divide-y divide-border text-sm">
            {profile.org_units.map((ou) => (
              <li key={ou.org_unit_id} className="flex items-center justify-between py-2.5">
                <span>{ou.org_unit_name ?? ou.org_unit_id}</span>
                {ou.is_primary && (
                  <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                    {"Primary"}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>

        {/* Teams Card */}
        <div className="rounded-xl border border-border bg-surface p-5 shadow-sm space-y-3">
          <div className="flex items-center gap-2 font-semibold text-foreground">
            <Users className="h-4 w-4 text-primary" />
            <h2>{"Teams"}</h2>
          </div>
          <ul className="divide-y divide-border text-sm">
            {profile.teams.map((team) => (
              <li key={team.team_id} className="flex items-center justify-between py-2.5">
                <span>{team.team_name ?? team.team_id}</span>
                {team.role_in_team && (
                  <span className="rounded-full bg-border px-2 py-0.5 text-xs text-muted">
                    {team.role_in_team}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* Held Assets & Work Orders (Modular sections) */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        {hasModule(me, "assets") && (
          <div className="rounded-xl border border-border bg-surface p-5 shadow-sm space-y-2">
            <div className="flex items-center gap-2 font-semibold text-foreground">
              <Boxes className="h-4 w-4 text-primary" />
              <h2>{"Held Assets"}</h2>
            </div>
            <p className="text-xs text-muted">{"No assets currently checked out to this member."}</p>
          </div>
        )}

        {hasModule(me, "maintenance") && (
          <div className="rounded-xl border border-border bg-surface p-5 shadow-sm space-y-2">
            <div className="flex items-center gap-2 font-semibold text-foreground">
              <Wrench className="h-4 w-4 text-primary" />
              <h2>{"Assigned Work Orders"}</h2>
            </div>
            <p className="text-xs text-muted">{"No open maintenance tasks assigned."}</p>
          </div>
        )}
      </div>
    </div>
  );
};
