"""Hills entry point of the LOCAL-ONLY beat-the-hotspot-quantum variant.

NOT LEADERBOARD COMPARABLE. This variant accepts an optional `quantum` block in
submission.json and evaluates the hybrid quantum + classical system. See
README_QUANTUM_VARIANT.md. The unmodified original entry point is kept verbatim in
eval_original.py and is what the classical core ultimately calls.

Inside the pinned container (no scipy) a submission with a `quantum` block cannot be
evaluated; use `python eval_quantum.py <dir>` on the host instead (see the README).
"""

from eval_original import HOTSPOT, _ensure_executable  # noqa: F401  (kept for tests/test_hill.py)
from eval_quantum import eval  # noqa: F401
