# SPDX-FileCopyrightText: 2026 TinyPhi
# SPDX-License-Identifier: AGPL-3.0-only
"""The asset edit audit row never holds encrypted values, before or after (§B8.1).

`_update_audit_states` copied every changed column into `before_state`, so editing an encrypted
custom field wrote the old ciphertext map into the audit log; only `after_state` was reduced to
field names.
"""

from __future__ import annotations

import json
from uuid import uuid4

from app.modules.assets.service import _update_audit_states

OLD_CIPHERTEXT = "vault:v1:old-ciphertext-value"
NEW_CIPHERTEXT = "vault:v1:new-ciphertext-value"


def test_encrypted_fields_are_recorded_by_name_only_on_both_sides() -> None:
    current = {
        "name": "Before",
        "custom_fields": {"colour": "red"},
        "encrypted_fields": {"serial_secret": OLD_CIPHERTEXT, "pin": OLD_CIPHERTEXT},
    }
    sets = {
        "name": "After",
        "custom_fields": {"colour": "blue"},
        "encrypted_fields": {"serial_secret": NEW_CIPHERTEXT, "pin": NEW_CIPHERTEXT},
    }

    before, after = _update_audit_states(current, sets)

    dumped = json.dumps([before, after])
    assert OLD_CIPHERTEXT not in dumped
    assert NEW_CIPHERTEXT not in dumped
    assert "encrypted_fields" not in before
    assert "custom_fields" not in before
    assert before == {"name": "Before"}
    assert after == {"name": "After", "encrypted_fields_changed": ["pin", "serial_secret"]}


def test_plain_column_changes_are_kept_and_uuids_are_strings() -> None:
    old_unit, new_unit = uuid4(), uuid4()
    before, after = _update_audit_states(
        {"owner_org_unit_id": old_unit, "name": "Same"}, {"owner_org_unit_id": new_unit}
    )
    assert before == {"owner_org_unit_id": str(old_unit)}
    assert after == {"owner_org_unit_id": str(new_unit)}
