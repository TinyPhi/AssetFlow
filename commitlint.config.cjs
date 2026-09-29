// SPDX-FileCopyrightText: 2026 TinyPhi
// SPDX-License-Identifier: AGPL-3.0-only

// Commit message rules (master plan §B12.3, §C12).
// Conventional Commits with a scope. Types and scopes exactly as in §B12.3.
// A new provider or channel adds its scope here in the same PR.
// No Signed-off-by trailer is required (contributors accept the CLA instead).

const FORBIDDEN_SCOPES = ["claude"];

module.exports = {
  extends: ["@commitlint/config-conventional"],
  plugins: [
    {
      rules: {
        // Rejects forbidden scopes explicitly, even if someone later adds them to scope-enum.
        "scope-forbidden": (parsed, when = "always", value = []) => {
          const scopes = (parsed.scope || "")
            .split(/[,/\\]/)
            .map((s) => s.trim().toLowerCase())
            .filter(Boolean);
          const hits = scopes.filter((s) => value.includes(s));
          const ok = when === "never" ? hits.length > 0 : hits.length === 0;
          return [ok, `scope must not be one of [${value.join(", ")}]; found: ${hits.join(", ")}`];
        },
      },
    },
  ],
  rules: {
    "type-enum": [
      2,
      "always",
      ["feat", "fix", "docs", "refactor", "perf", "test", "build", "ci", "chore", "security", "revert"],
    ],
    "scope-empty": [2, "never"],
    "scope-enum": [
      2,
      "always",
      [
        "core",
        "organization",
        "assets",
        "maintenance",
        "notifications",
        "audit",
        "workflow-engine",
        "automation-engine",
        "provider-oidc",
        "provider-openbao",
        "provider-file",
        "provider-otel",
        "provider-postgres",
        "channel-inapp",
        "channel-email",
        "channel-webhook",
        "worker",
        "web",
        "config",
        "deploy",
        "docs",
        "ci",
      ],
    ],
    "scope-forbidden": [2, "always", FORBIDDEN_SCOPES],
    "header-max-length": [2, "always", 72],
    "subject-case": [2, "always", "lower-case"],
    "signed-off-by": [0],
  },
};
