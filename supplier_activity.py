"""Canonical current supplier qualification activity used across PQM."""


def effective_active_sql(registry_alias="rc", framework_alias="f"):
    """SQL predicate for a qualification that is effective in the catalogue now."""
    rc, framework = registry_alias, framework_alias
    return f"""{rc}.status='active'
      AND LOWER(COALESCE({framework}.status,''))='active'
      AND (COALESCE(json_extract({framework}.raw_json,'$.qualificationPeriod.endDate'),'')=''
        OR date(substr(json_extract({framework}.raw_json,'$.qualificationPeriod.endDate'),1,10))>=date('now'))"""


def effective_inactive_sql(registry_alias="rc", framework_alias="f"):
    """Terminated or expired/non-current qualifications, excluding suspended ones."""
    rc = registry_alias
    return f"""{rc}.status='terminated' OR
      ({rc}.status='active' AND NOT ({effective_active_sql(registry_alias, framework_alias)}))"""
