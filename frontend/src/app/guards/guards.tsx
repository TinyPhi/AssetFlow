// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Route guards (§C4.9). UI hiding is a convenience only: every API route still checks permission and
// module itself, so a guard that lets someone through never grants anything.
import type React from "react";
import { useSyncExternalStore } from "react";
import { Navigate, Outlet, useLocation } from "react-router";
import { ErrorState, Skeleton } from "@/components/ui";
import { hasSession, subscribeSession } from "@/lib/auth";
import { can, hasModule, useMe, type ModuleKey } from "@/lib/permissions";
import { NotAuthorizedPage } from "@/app/pages/NotAuthorizedPage";

/** Signed-in members only; anyone else is sent to sign in (P7-02b builds the screen). */
export const RequireAuth: React.FC = () => {
  const signedIn = useSyncExternalStore(subscribeSession, hasSession);
  const location = useLocation();
  if (!signedIn) {
    return <Navigate to="/sign-in" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
};

interface AccessProps {
  allow: (me: NonNullable<ReturnType<typeof useMe>["data"]>) => boolean;
  children: React.ReactNode;
}

/** Waits for `GET /me`, then shows the children or the not-authorized screen. */
const Access: React.FC<AccessProps> = ({ allow, children }) => {
  const { data: me, isPending, isError, refetch } = useMe();
  if (isPending) return <Skeleton />;
  if (isError) {
    return (
      <ErrorState
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }
  return allow(me) ? <>{children}</> : <NotAuthorizedPage />;
};

interface RequirePermissionProps {
  permission: string;
  children: React.ReactNode;
}

export const RequirePermission: React.FC<RequirePermissionProps> = ({ permission, children }) => (
  <Access allow={(me) => can(me, permission)}>{children}</Access>
);

interface RequireModuleProps {
  module: ModuleKey;
  children: React.ReactNode;
}

export const RequireModule: React.FC<RequireModuleProps> = ({ module, children }) => (
  <Access allow={(me) => hasModule(me, module)}>{children}</Access>
);
