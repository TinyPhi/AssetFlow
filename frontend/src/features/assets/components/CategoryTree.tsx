// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

import type React from "react";
import { useMemo, useState } from "react";
import { useToast } from "@/app/toastContext";
import { EmptyState, ErrorState, Skeleton } from "@/components/ui";
import { t } from "@/lib/i18n";
import { useCategoryMutations, useCategoryRecords } from "../hooks/useCatalog";
import { useVocabulary } from "../hooks/useAssetDetail";
import { humanizeKey } from "../lib/asset-filter-params";
import {
  categoryCreateBody,
  categoryErrors,
  categoryUpdateBody,
  categoryValues,
  catalogFailure,
  EMPTY_CATEGORY,
  moveTargets,
  type CategoryFormValues,
} from "../lib/catalog-form";
import { treeOrder } from "../lib/hierarchy";
import type { CategoryRecord } from "../types";
import { BUTTON_CLASS, CONTROL_CLASS, PRIMARY_BUTTON_CLASS } from "./control-class";
import { ConfirmDialog } from "./ConfirmDialog";
import { Dialog } from "./Dialog";
import { FormField } from "./FormField";

const NBSP = " ";

type Action =
  | { kind: "create" }
  | { kind: "edit"; category: CategoryRecord }
  | { kind: "move"; category: CategoryRecord }
  | { kind: "archive"; category: CategoryRecord };

