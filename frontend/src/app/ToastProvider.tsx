// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";
import React, { useCallback, useMemo, useState } from "react";
import { ToastContext, type ToastItem, type ToastType } from "@/app/toastContext";
import { t } from "@/lib/i18n";

const TOAST_TIMEOUT_MS = 5000;

const TYPE_CLASSES: Record<ToastType, string> = {
  success: "bg-success-surface border-success text-success",
  warning: "bg-surface border-warning text-warning",
  danger: "bg-surface border-danger text-danger",
  info: "bg-surface border-border text-foreground",
};

const TYPE_ICONS = {
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
  info: Info,
} as const;

let toastCounter = 0;

function newToastId(): string {
  toastCounter += 1;
  return `toast-${Date.now().toString(36)}-${toastCounter.toString(36)}`;
}

export const ToastProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((item) => item.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: ToastType = "info") => {
      const id = newToastId();
      setToasts((prev) => [...prev, { id, type, message }]);
      setTimeout(() => {
        removeToast(id);
      }, TOAST_TIMEOUT_MS);
    },
    [removeToast],
  );

  const value = useMemo(() => ({ showToast, removeToast }), [showToast, removeToast]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <aside
        aria-label={t("app.toast.region_label")}
        className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none"
      >
        {toasts.map((toast) => {
          const Icon = TYPE_ICONS[toast.type];
          return (
            <div
              key={toast.id}
              role={toast.type === "danger" || toast.type === "warning" ? "alert" : "status"}
              className={`pointer-events-auto flex items-center justify-between p-3.5 rounded-lg border shadow-lg text-sm transition-all ${TYPE_CLASSES[toast.type]}`}
            >
              <div className="flex items-center gap-2.5">
                <Icon aria-hidden="true" className="h-5 w-5 flex-shrink-0" />
                <span>{toast.message}</span>
              </div>
              <button
                type="button"
                onClick={() => {
                  removeToast(toast.id);
                }}
                aria-label={t("app.toast.dismiss")}
                title={t("app.toast.dismiss")}
                className="p-1 rounded hover:opacity-80 transition-opacity"
              >
                <X aria-hidden="true" className="h-4 w-4" />
              </button>
            </div>
          );
        })}
      </aside>
    </ToastContext.Provider>
  );
};
