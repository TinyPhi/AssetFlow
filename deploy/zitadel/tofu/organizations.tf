# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# One Zitadel organization per AssetFlow organization, from config/organizations/*.yaml,
# each with a project grant for AssetFlow listing its allowed roles (§B5.5, decision 52).
# The token claim urn:zitadel:iam:user:resourceowner:id carries the organization id, which
# AssetFlow stores in organizations.idp_organization_id (output organization_ids).

locals {
  organization_files = fileset(var.organizations_dir, "*.yaml")
  organizations = {
    for f in local.organization_files :
    trimsuffix(f, ".yaml") => yamldecode(file("${var.organizations_dir}/${f}"))
  }
}

resource "zitadel_org" "org" {
  for_each = local.organizations
  name     = each.value.name

  lifecycle {
    precondition {
      condition     = try(each.value.slug, "") == each.key
      error_message = "Organization file ${each.key}.yaml: slug must equal the file name."
    }
    precondition {
      condition     = length(try(each.value.idp.granted_roles, [])) > 0 && alltrue([for r in try(each.value.idp.granted_roles, []) : contains(keys(local.roles), r)])
      error_message = "Organization file ${each.key}.yaml: idp.granted_roles must list AssetFlow project roles only."
    }
  }
}

resource "zitadel_project_grant" "assetflow" {
  for_each       = local.organizations
  org_id         = local.platform_org_id
  project_id     = zitadel_project.assetflow.id
  granted_org_id = zitadel_org.org[each.key].id
  role_keys      = each.value.idp.granted_roles

  depends_on = [zitadel_project_role.roles]
}
