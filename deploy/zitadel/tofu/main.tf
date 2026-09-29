# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
# Zitadel as code for AssetFlow (P2-10, P2-11, §B5.5, §B11.2, decisions 51 and 52).
# OpenTofu with the official Zitadel provider: https://registry.terraform.io/providers/zitadel/zitadel
# Applied by scripts/zitadel-apply.py (make zitadel-apply). State stays local and git-ignored:
# it holds the BFF client secret and a machine key, which the script copies into OpenBao.

terraform {
  required_version = ">= 1.8.0"
  required_providers {
    zitadel = {
      source  = "zitadel/zitadel"
      version = "~> 3.8"
    }
  }
}

# Authenticates as the first-instance "tofu-admin" machine user (deploy/zitadel/steps.yaml).
# Its key lives in OpenBao; zitadel-apply writes it to a temporary file for the run only.
provider "zitadel" {
  domain           = var.zitadel_domain
  insecure         = var.zitadel_insecure
  port             = var.zitadel_port
  jwt_profile_file = var.jwt_profile_file
}
