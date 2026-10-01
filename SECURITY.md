# Security Policy

The AssetFlow team and TinyPhi take the security of AssetFlow and its multi-tenant data isolation seriously. We appreciate the responsible disclosure of security vulnerabilities by security researchers and the community.

---

## 1. Supported Versions

Security updates and patches are provided for the following versions:

| Version | Supported | Notes |
| --- | :---: | --- |
| `1.0.x` | Yes | Current active development and stable release line |
| `< 1.0.0` | No | Pre-release and development snapshots |

---

## 2. Reporting a Vulnerability

**Do NOT report security vulnerabilities via public GitHub issues, discussions, or pull requests.**

If you discover a security vulnerability or multi-tenant isolation flaw in AssetFlow, please report it privately:

- **Email**: Send an encrypted or plain report to **`security@tinyphi.com`**.
- **Subject**: `[SECURITY VULNERABILITY] <Component>: <Brief Description>`
- **Content**:
  1. Detailed description of the vulnerability and attack vector.
  2. Proof-of-concept (PoC) code or step-by-step reproduction instructions.
  3. The versions of AssetFlow, PostgreSQL, and providers tested.
  4. Any potential mitigating configurations or workarounds.

---

## 3. Response Process & SLA

Upon receiving a private vulnerability report, the security team commits to the following timeline:

1. **Initial Acknowledgment**: Within **48 hours**, confirming receipt of the report.
2. **Triage & Assessment**: Within **5 business days**, confirming reproduction and assessing severity (CVSS score).
3. **Remediation & Patch**:
   - **Critical / High Severity** (e.g., cross-tenant data leakage, remote code execution, authentication bypass): Patch developed and tested within **14 days**.
   - **Medium / Low Severity**: Patch scheduled for the next regular maintenance release (within **30 days**).
4. **Coordinated Disclosure**: A public security advisory (GHSA) and CVE identifier will be issued alongside the release of the patched version. Reporters who adhere to coordinated disclosure will be credited in the release notes.

---

## 4. Protected Security Paths (§C5.8)

Changes to the following sensitive components require mandatory security review and cannot be merged without explicit sign-off from a designated Security Reviewer:

- `backend/app/core/permissions`
- `backend/app/core/auth_middleware.py`
- `backend/app/core/db`
- `backend/app/providers/auth/`
- `backend/app/providers/secrets/`
- `backend/app/channels/base.py`
- `backend/app/modules/organization/`
- `backend/app/modules/assets/qr/public`
- `backend/migrations/`
- `deploy/`
- `.github/workflows/`
- `scripts/check-*`
