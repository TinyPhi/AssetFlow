# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Project AssetFlow and its roles (§B5.5, §B7.2 default roles).
# The project belongs to the platform organization (the provider's default organization,
# "AssetFlow Platform" from deploy/zitadel/steps.yaml) and is shared through project grants.

# The platform organization created by Zitadel setup (FirstInstance.Org.Name).
data "zitadel_orgs" "platform" {
  name        = var.platform_org_name
  name_method = "TEXT_QUERY_METHOD_EQUALS"
}

locals {
  platform_org_id = one(data.zitadel_orgs.platform.ids)

  # Default roles, master plan §B7.2. Keys are the AssetFlow role keys.
  roles = {
    viewer              = "Viewer"
    technician          = "Technician"
    team_lead           = "Team lead"
    asset_manager       = "Asset manager"
    maintenance_planner = "Maintenance planner"
    org_unit_manager    = "Org unit manager"
    admin               = "Organization admin"
  }
}

resource "zitadel_project" "assetflow" {
  org_id = local.platform_org_id
  name   = "AssetFlow"
  # "Assert roles on authentication": roles are in the tokens (checked locally against JWKS).
  project_role_assertion = true
  # Only users with at least one role of this project may sign in.
  project_role_check = true
  # Only users of organizations that have a grant for this project may sign in.
  has_project_check        = true
  private_labeling_setting = "PRIVATE_LABELING_SETTING_ENFORCE_PROJECT_RESOURCE_OWNER_POLICY"
}

resource "zitadel_project_role" "roles" {
  for_each     = local.roles
  org_id       = local.platform_org_id
  project_id   = zitadel_project.assetflow.id
  role_key     = each.key
  display_name = each.value
  group        = "assetflow"
}
