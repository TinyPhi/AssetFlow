# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Inputs for the Zitadel configuration. No secrets: the key file path is passed at run time.

variable "zitadel_domain" {
  type        = string
  description = "Zitadel external domain (ZITADEL_DOMAIN in deploy/compose.full.yml)."
  default     = "localhost"
}

variable "zitadel_port" {
  type        = string
  description = "Zitadel external port (ZITADEL_EXTERNALPORT)."
  default     = "8081"
}

variable "zitadel_insecure" {
  type        = bool
  description = "Use HTTP instead of HTTPS (true only for localhost, when ZITADEL_EXTERNALSECURE=false)."
  default     = true
}

variable "jwt_profile_file" {
  type        = string
  description = "Path to the tofu-admin machine key JSON (temporary file written by zitadel-apply)."
  default     = ""
}

variable "platform_org_name" {
  type        = string
  description = "Name of the platform organization that owns the project (deploy/zitadel/steps.yaml)."
  default     = "AssetFlow Platform"
}

variable "organizations_dir" {
  type        = string
  description = "Directory with one YAML file per AssetFlow organization (config/organizations)."
  default     = "../../../config/organizations"
}

variable "dev_mode" {
  type        = bool
  description = "Allow http:// redirect URIs (local development only)."
  default     = true
}

variable "web_redirect_uris" {
  type        = list(string)
  description = "Redirect URIs of the public web client (PKCE)."
  default     = ["http://localhost:5173/auth/callback"]
}

variable "web_post_logout_uris" {
  type        = list(string)
  description = "Post-logout redirect URIs of the public web client."
  default     = ["http://localhost:5173/"]
}

variable "bff_redirect_uris" {
  type        = list(string)
  description = "Redirect URIs of the server-side (BFF) client."
  default     = ["http://localhost:8080/api/v1/auth/callback"]
}

variable "bff_post_logout_uris" {
  type        = list(string)
  description = "Post-logout redirect URIs of the server-side (BFF) client."
  default     = ["http://localhost:8080/"]
}

variable "automation_key_expiration" {
  type        = string
  description = "Expiration (RFC 3339) of the automation machine key; rotate before it."
  default     = "2027-12-31T00:00:00Z"
}
