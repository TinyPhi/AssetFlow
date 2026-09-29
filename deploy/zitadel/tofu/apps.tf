# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Applications and the automation machine user (§B5.5, §B11.2, §B11.4, decision 51).
# Both applications use JWT access tokens with roles asserted, so AssetFlow checks tokens
# locally against the cached JWKS. The project id is in the audience when the sign-in asks
# for the scope urn:zitadel:iam:org:project:id:{projectId}:aud (docs/operations/zitadel.md).

# Public web client: user agent, authorization code + PKCE, no client secret.
resource "zitadel_application_oidc" "web" {
  org_id                      = local.platform_org_id
  project_id                  = zitadel_project.assetflow.id
  name                        = "assetflow-web"
  app_type                    = "OIDC_APP_TYPE_USER_AGENT"
  auth_method_type            = "OIDC_AUTH_METHOD_TYPE_NONE"
  response_types              = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                 = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE"]
  redirect_uris               = var.web_redirect_uris
  post_logout_redirect_uris   = var.web_post_logout_uris
  dev_mode                    = var.dev_mode
  access_token_type           = "OIDC_TOKEN_TYPE_JWT"
  access_token_role_assertion = true
  id_token_role_assertion     = true
  id_token_userinfo_assertion = true
  clock_skew                  = "0s"
}

# Server-side (BFF) client: confidential. Its client secret is copied to OpenBao
# secret/assetflow/idp by scripts/zitadel-apply.py and never committed.
resource "zitadel_application_oidc" "bff" {
  org_id                      = local.platform_org_id
  project_id                  = zitadel_project.assetflow.id
  name                        = "assetflow-bff"
  app_type                    = "OIDC_APP_TYPE_WEB"
  auth_method_type            = "OIDC_AUTH_METHOD_TYPE_BASIC"
  response_types              = ["OIDC_RESPONSE_TYPE_CODE"]
  grant_types                 = ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"]
  redirect_uris               = var.bff_redirect_uris
  post_logout_redirect_uris   = var.bff_post_logout_uris
  dev_mode                    = var.dev_mode
  access_token_type           = "OIDC_TOKEN_TYPE_JWT"
  access_token_role_assertion = true
  id_token_role_assertion     = true
  id_token_userinfo_assertion = true
  clock_skew                  = "0s"
}

# Machine user for the organization onboarding automation (§B5.7, --create-idp-org).
resource "zitadel_machine_user" "automation" {
  org_id            = local.platform_org_id
  user_name         = "assetflow-automation"
  name              = "AssetFlow organization automation"
  description       = "Creates Zitadel organizations and project grants for AssetFlow organizations"
  access_token_type = "ACCESS_TOKEN_TYPE_JWT"
}

# Its key is copied to OpenBao secret/assetflow/zitadel/automation-key by zitadel-apply.
resource "zitadel_machine_key" "automation" {
  org_id          = local.platform_org_id
  user_id         = zitadel_machine_user.automation.id
  key_type        = "KEY_TYPE_JSON"
  expiration_date = var.automation_key_expiration
}

# Instance-level role to manage organizations and their project grants.
resource "zitadel_instance_member" "automation" {
  user_id = zitadel_machine_user.automation.id
  roles   = ["IAM_ORG_MANAGER"]
}
