#!/usr/bin/env python3
"""Stop: refuse a false "done".

If the agent ran `af.py done` but source or test changes are still uncommitted,
the session may not end. Uses `stop_hook_active` to avoid an endless loop.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import state as s  # noqa: E402


def main() -> None:
    data = s.hook_input()
    if data.get("stop_hook_active"):
        s.allow()
    if s.read_state("claimed-done") is None:
        s.allow()
    left = [f for f in s.changed_files() if s.is_source(f) or s.is_test(f)]
    if not left:
        s.delete_state("claimed-done")
        s.allow()
    print(
        json.dumps(
            {
                "decision": "block",
                "reason": "You claimed done, but these changes are uncommitted: "
                + ", ".join(left[:10])
                + ". Finish the SHIP stage (af.py status shows what is open), or say LOOP_BLOCKED with the reason.",
            }
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
