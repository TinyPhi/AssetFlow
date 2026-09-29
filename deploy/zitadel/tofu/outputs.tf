# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Outputs read by scripts/zitadel-apply.py. Sensitive values go to OpenBao, never to git.

output "project_id" {
  description = "AssetFlow project id (audience scope urn:zitadel:iam:org:project:id:{projectId}:aud)."
  value       = zitadel_project.assetflow.id
}

output "web_client_id" {
  description = "Client id of the public web client (PKCE, no secret)."
  value       = nonsensitive(zitadel_application_oidc.web.client_id) # public identifier
}

output "bff_client_id" {
  description = "Client id of the server-side (BFF) client."
  value       = nonsensitive(zitadel_application_oidc.bff.client_id) # public identifier
}

output "bff_client_secret" {
  description = "BFF client secret; copied to OpenBao secret/assetflow/idp."
  value       = zitadel_application_oidc.bff.client_secret
  sensitive   = true
}

output "automation_key" {
  description = "Automation machine key JSON; copied to OpenBao secret/assetflow/zitadel/automation-key."
  value       = zitadel_machine_key.automation.key_details
  sensitive   = true
}

output "organization_ids" {
  description = "Zitadel organization id per AssetFlow organization slug (organizations.idp_organization_id)."
  value       = { for slug, org in zitadel_org.org : slug => org.id }
}
