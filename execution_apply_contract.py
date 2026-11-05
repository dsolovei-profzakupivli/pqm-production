"""Shared capability switch for resumable Execution API Apply."""

# Sandbox is the only enabled environment in this candidate. Production keeps
# its legacy single-call receipt until a separately approved Apps Script release.
CHECKPOINT_APPLY_ENVIRONMENTS = frozenset({'SANDBOX'})


def checkpoint_apply_enabled(environment):
    return environment in CHECKPOINT_APPLY_ENVIRONMENTS
