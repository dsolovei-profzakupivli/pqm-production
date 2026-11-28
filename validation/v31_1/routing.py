"""Exact version ownership; no suite-wide baseline fallback."""
MODULES = (
    'test_edr_sync_v2', 'test_supplier_edr_apply_v31', 'test_sandbox_edr_review',
    'test_edr_monitoring', 'test_edr_google_nazk_manager_reconcile',
    'test_supplier_edr_dates', 'test_permanent_edr_sync_safety',
)
HISTORICAL_MESSAGES_MODULES = (
    'test_sandbox_messages_integrity',
    'test_sandbox_nazk_messages_integrated_integrity',
    'test_nazk_authority_request_integrity',
    'test_messages_historical_line_endings',
)
SUPERSEDED = {
    'test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_missing_current_verification_date_does_not_replace_existing_facts': {
        'old': 'Missing PQM verification date blocks replacing existing facts.',
        'new': 'Missing date alone is not a conflict; valid first Google I/L is admitted subject to independent guards.',
        'regressions': ['CurrentTests.test_first_pair_missing_empty_profile_and_existing_facts', 'CurrentTests.test_yupiter_accepts_initial_pair_despite_undated_facts'],
    },
    'test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_empty_and_malformed_pqm_verification_dates_have_distinct_reasons': {
        'old': 'Both empty and malformed previous dates block, with distinct reasons.',
        'new': 'Empty previous date admits valid first I/L; malformed nonempty previous date still blocks.',
        'regressions': ['CurrentTests.test_first_pair_missing_empty_profile_and_existing_facts', 'CurrentTests.test_malformed_nonempty_prior_date_is_not_a_first_check'],
    },
    'test_permanent_edr_sync_safety.PermanentSyncSafetyTests.test_google_no_information_is_not_imported_as_factual_or_current_status': {
        'old': 'NoInfo Google status is tolerated without importing a new factual status.',
        'new': 'Blank/NoInfo Google E is always an explicit row conflict, including XLSX.',
        'regressions': ['CurrentTests.test_google_status_required_independent_of_time_and_current_status', 'CurrentTests.test_empty_unknown_google_status_always_conflicts_and_is_read_only'],
    },
}
ENTRYPOINTS = ('github', 'local', 'container', 'predeploy')
CONTRACT = 'sandbox-v31.1'

V31_INFRASTRUCTURE_CONTRACT = 'test_release_gate_infrastructure.ReleaseGateInfrastructureTests.test_workflow_routes_historical_and_current_integrity_checks'
