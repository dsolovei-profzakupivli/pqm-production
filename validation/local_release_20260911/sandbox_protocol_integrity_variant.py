"""Exact, baseline-bound integrity exception for the approved protocol work."""
import copy
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "test_sandbox_protocol_integrity_variant.json"
ADDITIONAL_CONTRACTS = (ROOT / "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json",)
ADDITIONAL_CONTRACT_SHA256 = {
    "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json":
        "5e3f40aef120ebe39fcc87d0cdf2b368dec3fe3f3e28aa5ff71ffb9dac3bd2be"
}
CAT_CONTRACT = ROOT / "test_sandbox_permanent_cat_integrity_variant.json"
CAT_CONTRACT_SHA256 = "8d6987a16dcefd471a142d3a5e18bb6e50d63f9589f2dd1f75fcdee546267a3c"
CAT_VARIANT_ID = "sandbox-permanent-cat-v1"
CAT_BASELINE = "20fe5a4c721ab60ae95ba44816b79d00a6e3df8d"
CAT_APPROVED_SCOPE = {
    "sandbox-only-permanent-cat-season-switch",
    "kyiv-season-transition-in-open-tab",
    "preserve-existing-personal-cat-preference",
    "season-independent-eye-tracking-and-blinking",
    "approved-no-hat-cat-asset",
}
CAT_PRODUCT_FILES = {
    "sandbox_runtime.py",
    "halloween_motion.js",
    "halloween_cat_season.js",
    "halloween_cat_season.css",
    "assets/pqm-cat-no-hat.png",
}
CAT_PROTECTED_FILES = {"app.js", "server.py"}
CAT_PROTECTED_SHA256 = {
    "app.js": "ed905909640e43cac001e5bce492aa5e43fdda40c798dcc22c7316aeaa44e9f6",
    "server.py": "8ad164eafb0caeefbd896a1584886bd24311634c416b64fe0cb10459f24236b9",
}
CAT_GUARDED_FILES = {
    "application_selection.js", "assets/halloween-witch-cat.webp",
    "assets/halloween-workqueue-dark.webp", "assets/halloween-workqueue-light.webp",
    "auth_access.py", "background_jobs.py", "bulk_application_save.js", "filters.css",
    "google_writer_execution.py", "halloween.css", "halloween.js", "halloween_motion.css",
    "halloween_season.js", "index.html", "metadata/template_legacy_tokens.v1.json",
    "modules.css", "operational_task_officers.js", "protocol_supplier_names.py",
    "registry_popovers.js", "sandbox_amcu.py", "sandbox_contrast.js", "sandbox_documents.py",
    "sandbox_theme.css", "scheduler_runtime.py", "styles.css", "template_catalog.py",
    "templates/violation_protocols/decline_individual_review.docx", "theme.css", "theme_ui.js",
    "ui_final.js", "ui_tz2.js", "violation_protocol_docx.py",
}
BASELINE = "565a2fff45675b6b49feb90edf67e83aa2af4a7b"
VARIANT_ID = "sandbox-universal-decline-p49-3-v1"
APPROVED_SCOPE = {
    "explicit_individual_decline_protocol_choice",
    "current_review_notes_confirmation",
    "server_validation_of_individual_decline_type",
    "p49_reference_from_request_basis",
    "individual_protocol_docx_context",
    "p49_3_winner_date_exemption_only",
}
PRODUCT_FILES = {
    "app.js",
    "server.py",
    "template_catalog.py",
    "violation_protocol_docx.py",
    "metadata/template_legacy_tokens.v1.json",
    "templates/violation_protocols/decline_individual_review.docx",
}
TEXT_PRODUCT_FILES = PRODUCT_FILES - {
    "templates/violation_protocols/decline_individual_review.docx",
}
PROTECTED_FILES = {"app.js", "server.py"}
HASH_FORMAT = "Full-file SHA-256; text files use canonical LF line endings, DOCX is hashed byte-for-byte"

NAZK_CONTRACT = ROOT / "test_sandbox_nazk_columns_integrity_variant.json"
NAZK_CONTRACT_SHA256 = "c4137c780c1640e6f23ab5f20c831b591e9c5577758e56c4b7af1ea94c5b6450"
NAZK_BASELINE = "de774010d99e3786eb6ff8308bba78aa5c9a6f13"
NAZK_VARIANT_ID = "sandbox-nazk-three-columns-v1"
NAZK_PRODUCTS = {"app.js", "index.html", "styles.css", "nazk_registry_evidence.py", "reference_directories.py"}
NAZK_EXTRA_GUARDS = {
    "operational_tasks.py", "uo_work_queue.py", "nazk_workflow.py", "nazk_evidence.py",
    "test_sandbox_protocol_integrity_variant.json",
    "test_sandbox_protocol_integrity_variant_protocol-fixes-v2.json",
    "test_sandbox_permanent_cat_integrity_variant.json",
}
NAZK_SCOPE = {
    "three_trailing_columns_in_two_existing_nazk_tables",
    "read_only_decree_projection_from_saved_raw",
    "preserve_exact_decree_strings_and_court_fields",
    "omit_full_raw_from_browser",
}
NAZK_BASELINE_FIXTURE = ROOT / "validation/fixtures/nazk_integrity_baseline_de77401.zip"
NAZK_BASELINE_FIXTURE_SHA256 = "94e14820ee3b9720cd80a04a2dfdf5165ee59e8da6e95655c1564741c1705ba0"
ADMIN_HISTORY_CONTRACT = ROOT / "test_sandbox_admin_officer_link_integrity_variant.json"
ADMIN_HISTORY_CONTRACT_SHA256 = "1859d4772ae3febfb0df4be1385d334711104a1130d931294ce0cfb5a1ed9912"
ADMIN_CONTRACT = ROOT / "test_sandbox_admin_officer_link_integrity_v2.json"
ADMIN_CONTRACT_SHA256 = "0c908cbc2c8da86c7ff95d8e09d99122c8524090d9205e3d4951678fda66db08"
ADMIN_V3_DELTA = ROOT / "test_sandbox_admin_officer_link_integrity_v3.json"
ADMIN_V3_DELTA_SHA256 = "cb13dfe806ca884acaea7392c4fc8fc44ae86149eea5378934dad08d077da030"
ADMIN_PRODUCT_FILES = {"app.js", "auth_access.py", "auth_ui.js", "index.html", "server.py", "styles.css"}
ADMIN_GUARDED_FILES = {
    "application_selection.js", "assets/halloween-witch-cat.webp",
    "assets/halloween-workqueue-dark.webp", "assets/halloween-workqueue-light.webp",
    "assets/pqm-cat-no-hat.png", "background_jobs.py", "bulk_application_save.js",
    "filters.css", "google_writer_execution.py", "halloween.css", "halloween.js",
    "halloween_cat_season.css", "halloween_cat_season.js", "halloween_motion.css",
    "halloween_motion.js", "halloween_season.js", "metadata/template_legacy_tokens.v1.json",
    "modules.css", "nazk_registry_evidence.py", "operational_task_officers.js",
    "protocol_supplier_names.py", "reference_directories.py", "registry_popovers.js",
    "sandbox_amcu.py", "sandbox_contrast.js", "sandbox_documents.py", "sandbox_runtime.py",
    "sandbox_theme.css", "scheduler_runtime.py", "template_catalog.py",
    "templates/violation_protocols/decline_individual_review.docx", "theme.css",
    "theme_ui.js", "ui_final.js", "ui_tz2.js", "violation_protocol_docx.py",
}
ADMIN_PROTECTED_FILES = {"app.js", "server.py"}
ADMIN_SCOPE = {
    "separate_officer_directory_and_access_tabs",
    "preserve_existing_access_management_sections_and_handlers",
    "preserve_admin_officer_id_independently_of_role",
    "preserve_officer_id_on_omitted_field_updates",
    "admin_only_access_to_administration_section",
}
ADMIN_HASH_FORMAT = "Full-file SHA-256; text files use canonical LF line endings, binary assets are hashed byte-for-byte"
UI_CANDIDATE_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum.json"
UI_CANDIDATE_DELTA_SHA256 = "da4a79667f29e7e1f9ac7d1394dae99cfd225bd38c6da286e5822dd0ac86d284"
UI_CANDIDATE_ID = "sandbox-ui-integrated-d457-v1"
UI_CANDIDATE_V2_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v2.json"
UI_CANDIDATE_V2_DELTA_SHA256 = "ee4b837875836ba2807fff5752528898e26b1b554b853ba3bc5de76d2166c427"
UI_CANDIDATE_V2_ID = "sandbox-ui-integrated-d457-v2"
UI_CANDIDATE_V3_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v3.json"
UI_CANDIDATE_V3_DELTA_SHA256 = "46b3e905c401fd8e45fd8e8bf07d2d9350b5da68dc25c1ad68abb45d3b857d95"
UI_CANDIDATE_V3_ID = "sandbox-ui-integrated-d457-v3"
UI_CANDIDATE_V4_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v4.json"
UI_CANDIDATE_V4_DELTA_SHA256 = "e3097ff818c1b17dafdd7b29c92e3b335c28533de3a423d1b320221e90bf505b"
UI_CANDIDATE_V4_ID = "sandbox-ui-integrated-d457-v4"
UI_CANDIDATE_V5_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v5.json"
UI_CANDIDATE_V5_DELTA_SHA256 = "1f210bc192fcf3080a6027a7fca28a45fe8403def013e95088e21be7e4495cee"
UI_CANDIDATE_V5_ID = "sandbox-ui-integrated-d457-v5"

UI_CANDIDATE_V6_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v6.json"
UI_CANDIDATE_V6_DELTA_SHA256 = "48d59f1e4ae91a7b56c5610b6832be94549414cf470202a7941b3d2b9913c68d"
UI_CANDIDATE_V6_ID = "sandbox-ui-integrated-d457-v6"
UI_CANDIDATE_V7_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v7.json"
UI_CANDIDATE_V7_DELTA_SHA256 = "1ecc1a6c40e06eea3f4911c04e07b6357a867dc1e3b0aee2bcdce21941609b79"
UI_CANDIDATE_V7_ID = "sandbox-ui-integrated-d457-v7"
UI_CANDIDATE_V8_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v8.json"
UI_CANDIDATE_V8_DELTA_SHA256 = "cd9d0225591ff9d8ba588f18032326aacd802ab8ccc052c26c701825e8a41143"
UI_CANDIDATE_V8_ID = "sandbox-ui-integrated-d457-v8"
UI_CANDIDATE_V9_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v9.json"
UI_CANDIDATE_V9_DELTA_SHA256 = "9174865a6bb15c77d10eff92d71c32d5334df734cf5785515442d320953a17c1"
UI_CANDIDATE_V9_ID = "sandbox-ui-integrated-d457-v9"
UI_CANDIDATE_V10_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v10.json"
UI_CANDIDATE_V10_DELTA_SHA256 = "b86d31c108801bf4d076afdc3a49a7ae0749d2508ba44473b52c4fff2571c615"
UI_CANDIDATE_V10_ID = "sandbox-ui-integrated-d457-v10"
UI_CANDIDATE_V11_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v11.json"
UI_CANDIDATE_V11_DELTA_SHA256 = "3afe652651a359664a0cd31295c6dd9689e2ac92fb3cd45064e77e4ef562700b"
UI_CANDIDATE_V11_ID = "sandbox-ui-integrated-d457-v11"
UI_CANDIDATE_V12_DELTA = ROOT / "test_sandbox_ui_integrated_d457_integrity_addendum_v12.json"
UI_CANDIDATE_V12_DELTA_SHA256 = "a08b5eb0abc8289e324f7246b52266c8f0bca85766afee85c4bdf7a66dcb3d7f"
UI_CANDIDATE_V12_ID = "sandbox-ui-integrated-d457-v12"
UI_CANDIDATE_V6_SCOPE = {'browser_regressions_cover_one_click_roles_themes_and_saved_forms',
 'new_protocol_docx_uses_saved_card_declension_overrides_and_pdf_uses_current_docx',
 'permanent_card_declension_actions_for_customer_and_supplier',
 'preserve_review_card_draft_while_saving_declension_override',
 'read_only_declension_forms_for_viewers_and_existing_editor_for_managers'}
UI_CANDIDATE_V6_PRODUCT_OVERRIDES = {'app.js', 'test_sandbox_ui_integrated_d457_integrity.py', 'styles.css'}
UI_CANDIDATE_V6_PROTECTED_OVERRIDES = {'app.js'}
UI_CANDIDATE_V6_GUARD_OVERRIDES = {'validation/appeals_declension_card_browser.cjs',
 'validation/docker_release_gate.py',
 'validation/local_release_20260911/test_card_declension_generation.py',
 'validation/run_local_release.py',
 'validation/sandbox_appeals_declension_ui.cjs'}
UI_CANDIDATE_V7_SCOPE = {'collapse_protocol_name_provenance_block_by_default',
 'normalize_balanced_quotes_in_new_protocol_documents_and_metadata',
 'use_full_current_edr_name_when_short_name_is_missing_or_placeholder'}
UI_CANDIDATE_V7_PRODUCT_OVERRIDES = {'app.js',
 'document_quotes.py',
 'protocol_supplier_names.py',
 'server.py',
 'styles.css',
 'test_sandbox_ui_integrated_d457_integrity.py'}
UI_CANDIDATE_V7_PROTECTED_OVERRIDES = {'app.js', 'server.py'}
UI_CANDIDATE_V7_GUARD_OVERRIDES = {'test_document_quotes.py',
 'test_protocol_supplier_names.py',
 'validation/docker_release_gate.py',
 'validation/protocol_names_card_browser.cjs'}
UI_CANDIDATE_V8_SCOPE = {'keep_historical_integrity_suites_version_aware_for_integrated_ui_v8',
 'preserve_table_preferences_and_appeal_card_actions',
 'project_saved_appeal_justification_in_list_without_regeneration',
 'show_adaptive_scenario_summary_without_control_scenario_heading',
 'show_concise_saved_justification_with_read_only_one_click_viewer'}
UI_CANDIDATE_V8_PRODUCT_OVERRIDES = {'app.js',
 'index.html',
 'server.py',
 'styles.css',
 'test_sandbox_admin_officer_link_integrity.py',
 'test_sandbox_nazk_columns_integrity.py',
 'test_sandbox_ui_integrated_d457_integrity.py'}
UI_CANDIDATE_V8_PROTECTED_OVERRIDES = {'app.js', 'server.py'}
UI_CANDIDATE_V8_GUARD_OVERRIDES = {'test_sandbox_admin_officer_link_integrity.py',
 'test_sandbox_nazk_columns_integrity.py',
 'validation/appeals_justification_browser.cjs',
 'validation/docker_release_gate.py',
 'validation/local_release_20260911/test_violation_reports.py'}
UI_CANDIDATE_V9_SCOPE = {
    "remove_windows_only_playwright_fallbacks_and_browser_paths",
    "keep_historical_integrity_suites_version_aware_for_integrated_ui_v9",
    "run_appeals_browser_regressions_on_ubuntu_with_pinned_playwright_and_chromium",
    "keep_container_gate_limited_to_dependencies_in_the_application_image",
    "assert_browser_regressions_use_the_recorded_checkout_sha",
}
UI_CANDIDATE_V9_PRODUCT_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
UI_CANDIDATE_V9_GUARD_OVERRIDES = {
    ".github/workflows/release-checks.yml",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "validation/appeals_justification_browser.cjs",
    "validation/appeals_declension_card_browser.cjs",
    "validation/docker_release_gate.py",
    "validation/protocol_names_card_browser.cjs",
    "validation/run_local_release.py",
}
UI_CANDIDATE_V10_SCOPE = {
    "initialize_current_user_in_supplier_ux_fixture_and_assert_declension_editor_access_modes",
}
UI_CANDIDATE_V10_PRODUCT_OVERRIDES = {
    "validation/sandbox_supplier_ux.cjs",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
UI_CANDIDATE_V10_GUARD_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
}
UI_CANDIDATE_V11_SCOPE = {
    "model_declension_editor_read_only_lexical_state_in_vm_fixture_and_assert_permission_gated_saving",
}
UI_CANDIDATE_V11_PRODUCT_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "validation/appeals_declension_ui.cjs",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
UI_CANDIDATE_V11_GUARD_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "validation/appeals_declension_card_browser.cjs",
}
UI_CANDIDATE_V12_SCOPE = {
    "restore_adaptive_scenario_summary_in_appeals_table",
    "keep_saved_justification_in_separate_read_only_eye_viewer",
    "preserve_existing_appeals_column_preference_key_and_layout",
}
UI_CANDIDATE_V12_PRODUCT_OVERRIDES = {
    "app.js",
    "index.html",
    "styles.css",
    "test_sandbox_ui_integrated_d457_integrity.py",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "validation/appeals_justification_browser.cjs",
}
UI_CANDIDATE_V12_GUARD_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "validation/appeals_justification_browser.cjs",
}
UI_CANDIDATE_V12_PROTECTED_OVERRIDES = {"app.js"}
UI_CANDIDATE_PRODUCTS = {
    "app.js", "auth_access.py", "auth_ui.js", "edr_sync_v2.py",
    "history_columns.js", "index.html", "reference_directories.py", "server.py", "styles.css",
    "table_widths_ui.js",
}
UI_CANDIDATE_GUARDS = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "test_amcu_qualification_colors.py",
    "validation/column_settings_popover_browser.cjs",
    "validation/local_release_20260911/test_chat_widths.py",
    "validation/local_release_20260911/test_edr_sync_v2.py",
    "validation/local_release_20260911/test_history_ui_alignment.py",
    "validation/local_release_20260911/test_supplier_edr_filter.py",
    "validation/run_local_release.py",
    "validation/table_widths_native_browser.cjs",
    "validation/table_widths_unified_browser.cjs",
    "validation/nazk_toolbar_layout_browser.cjs",
    "validation/amcu_qualification_colors_browser.cjs",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
UI_CANDIDATE_SCOPE = {
    "account_and_table_scoped_personal_column_widths_admin_only",
    "drag_resizing_and_existing_width_menu_are_synchronized",
    "preserve_existing_supported_column_order_settings",
    "nazk_column_order_text_widths_history_alignment_and_compact_toolbar",
    "amcu_compact_toolbar_readable_rows_and_qualification_status_colors",
    "edr_future_check_date_fails_safe_and_inactive_markers_remain_purple",
    "officer_directory_toolbar_uses_one_desktop_row",
}
UI_CANDIDATE_V2_SCOPE = {
    "central_shared_width_order_visibility_for_non_personal_tables",
    "admin_only_shared_layout_update_and_reset_server_enforced",
    "preserve_personal_application_and_history_layouts_per_user",
    "legacy_width_records_merge_order_visibility_and_new_columns_default_visible",
    "no_local_storage_as_source_for_shared_table_layouts",
    "cross_browser_shared_layout_and_cross_account_personal_layout_isolation",
    "release_tests_use_isolated_source_paths_and_schema_fixtures",
}
UI_CANDIDATE_V2_PRODUCT_ADDITIONS = {
    "table_widths.py",
    "validation/sandbox_editable_smoke.py",
}
UI_CANDIDATE_V2_PRODUCT_OVERRIDES = {
    "app.js", "history_columns.js", "server.py", "styles.css", "table_widths_ui.js",
    "test_sandbox_nazk_columns_integrity.py", "test_sandbox_ui_integrated_d457_integrity.py",
    "validation/local_release_20260911/test_chat_widths.py",
    "validation/local_release_20260911/test_supplier_edr_filter.py",
    "validation/table_widths_native_browser.cjs",
    "validation/table_widths_unified_browser.cjs",
}
UI_CANDIDATE_V2_REMOVE_GUARDS = {
    "test_sandbox_nazk_columns_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
    "validation/local_release_20260911/test_chat_widths.py",
    "validation/local_release_20260911/test_supplier_edr_filter.py",
    "validation/table_widths_native_browser.cjs",
    "validation/table_widths_unified_browser.cjs",
}
UI_CANDIDATE_V2_GUARD_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_violation_report_kpi_facets.py",
    "validation/nazk_toolbar_layout_browser.cjs",
    "validation/column_settings_popover_browser.cjs",
    "validation/fixtures/column_widths_baseline_4625498.zip",
    "validation/run_local_release.py",
}
UI_CANDIDATE_V3_SCOPE = {
    "sandbox_smoke_uses_explicit_nonempty_synthetic_columns_for_owner_scope_permission_test",
}
UI_CANDIDATE_V3_PRODUCT_OVERRIDES = {
    "validation/sandbox_editable_smoke.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
}
UI_CANDIDATE_V4_SCOPE = {
    "supplier_hidden_table_widths_are_deferred_until_visible",
    "supplier_shared_widths_persist_across_hide_show_and_reload",
    "update_table_width_regressions_for_current_generic_visibility_installation",
}
UI_CANDIDATE_V4_PRODUCT_OVERRIDES = {
    "validation/sandbox_supplier_ux.cjs",
    "validation/table_widths_unified_browser.cjs",
    "test_sandbox_ui_integrated_d457_integrity.py",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
}
UI_CANDIDATE_V5_SCOPE = {
    "avoid_reordering_cells_when_actual_order_already_matches",
    "mutation_observer_settles_after_sort_filter_page_and_resize",
    "supplier_and_appeal_cards_open_on_one_ordinary_click",
    "run_shared_and_personal_layout_browser_matrix_against_both_exact_sources",
}
UI_CANDIDATE_V5_PRODUCT_OVERRIDES = {
    "table_widths_ui.js",
    "validation/card_click_stability.cjs",
    "validation/table_widths_unified_browser.cjs",
    "test_sandbox_ui_integrated_d457_integrity.py",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
}


def load_nazk_contract(cat):
    raw = NAZK_CONTRACT.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != NAZK_CONTRACT_SHA256:
        raise AssertionError("Changed pinned NAZK integrity manifest")
    contract = json.loads(raw.decode("utf-8"))
    expected_guards = (set(cat["product_files"]) | set(cat["guarded_files"]) |
                       NAZK_EXTRA_GUARDS) - NAZK_PRODUCTS - PROTECTED_FILES
    if (contract.get("variant_id") != NAZK_VARIANT_ID or
            contract.get("baseline_sha") != NAZK_BASELINE or
            contract.get("hash_format") != cat["hash_format"] or
            set(contract.get("approved_scope", [])) != NAZK_SCOPE or
            set(contract.get("product_files", {})) != NAZK_PRODUCTS or
            set(contract.get("protected_files", {})) != PROTECTED_FILES or
            set(contract.get("guarded_files", {})) != expected_guards):
        raise AssertionError("NAZK manifest does not match the exact approved scope")
    if contract["protected_files"]["server.py"] != cat["protected_files"]["server.py"]:
        raise AssertionError("NAZK must preserve the complete server protection")
    if contract["protected_files"]["app.js"]["sha256"] != contract["product_files"]["app.js"]["sha256"]:
        raise AssertionError("Conflicting NAZK app hashes")
    return contract


def nazk_baseline_content(relative):
    """Read exact historical bytes; never use the modified working copy."""
    raw = NAZK_BASELINE_FIXTURE.read_bytes()
    if sha256(raw) != NAZK_BASELINE_FIXTURE_SHA256:
        raise AssertionError("Changed pinned NAZK baseline fixture")
    with zipfile.ZipFile(NAZK_BASELINE_FIXTURE) as archive:
        return archive.read(f"{NAZK_BASELINE}/{relative}")


def load_contract():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("variant_id") != VARIANT_ID or contract.get("baseline_sha") != BASELINE:
        raise AssertionError("Integrity-варіант не прив’язаний до погодженого Sandbox baseline")
    if contract.get("hash_format") != HASH_FORMAT:
        raise AssertionError("Змінився формат повнофайлових SHA-256 integrity-варіанта")
    if set(contract.get("approved_scope", [])) != APPROVED_SCOPE:
        raise AssertionError("Змінився погоджений склад функціональності integrity-варіанта")
    if set(contract.get("product_files", {})) != PRODUCT_FILES:
        raise AssertionError("Змінився точний перелік product-файлів integrity-варіанта")
    if set(contract.get("protected_files", {})) != PROTECTED_FILES:
        raise AssertionError("Integrity-варіант має захищати лише app.js і server.py")
    return contract


def load_contracts():
    """Load the immutable original exception plus separately pinned additions."""
    contracts = [load_contract()]
    for path in ADDITIONAL_CONTRACTS:
        raw = path.read_bytes()
        expected_contract_sha = ADDITIONAL_CONTRACT_SHA256.get(path.name)
        if not expected_contract_sha or sha256(raw.replace(b"\r\n", b"\n")) != expected_contract_sha:
            raise AssertionError("Змінено закріплений integrity-маніфест протоколів")
        contract = json.loads(raw.decode("utf-8"))
        if contract.get("baseline_sha") != "b2027e6d687bc4018a2720f10fae228ccff7b201":
            raise AssertionError("Integrity-варіант протоколів не прив’язаний до погодженого baseline")
        if contract.get("variant_id") != "sandbox-protocol-fixes-v2":
            raise AssertionError("Невідомий integrity-варіант протоколів")
        if contract.get("hash_format") != HASH_FORMAT:
            raise AssertionError("Змінився формат повнофайлових SHA-256 integrity-варіанта")
        if set(contract.get("product_files", {})) != {
            "app.js", "protocol_supplier_names.py", "styles.css", "violation_protocol_docx.py"
        }:
            raise AssertionError("Змінився точний перелік погоджених product-файлів")
        if set(contract.get("approved_scope", [])) != {
            "preserve_manual_document_review_state_without_discarding_unsaved_fields",
            "normalize_supplier_protocol_filename_presentation_only",
            "render_customer_unavailable_document_note_with_approved_formatting",
            "present_supplier_name_provenance_and_review_notes_confirmation",
        }:
            raise AssertionError("Змінився погоджений склад виправлень")
        if set(contract.get("protected_files", {})) != PROTECTED_FILES:
            raise AssertionError("Integrity-варіант має зберігати захист app.js і server.py")
        contracts.append(contract)
    cat_raw = CAT_CONTRACT.read_bytes()
    if sha256(cat_raw.replace(b"\r\n", b"\n")) != CAT_CONTRACT_SHA256:
        raise AssertionError("Змінено закріплений integrity-маніфест постійного котика")
    cat = json.loads(cat_raw.decode("utf-8"))
    if cat.get("variant_id") != CAT_VARIANT_ID or cat.get("baseline_sha") != CAT_BASELINE:
        raise AssertionError("Integrity-варіант котика не прив’язаний до погодженого Sandbox baseline")
    if cat.get("hash_format") != "Full-file SHA-256; text files use canonical LF line endings, binary assets are hashed byte-for-byte":
        raise AssertionError("Змінився формат повнофайлових SHA-256 integrity-варіанта котика")
    if set(cat.get("approved_scope", [])) != CAT_APPROVED_SCOPE:
        raise AssertionError("Змінився погоджений склад функціональності integrity-варіанта котика")
    if set(cat.get("product_files", {})) != CAT_PRODUCT_FILES:
        raise AssertionError("Змінився точний перелік product-файлів котика")
    if set(cat.get("protected_files", {})) != CAT_PROTECTED_FILES:
        raise AssertionError("Integrity-варіант котика має захищати app.js і server.py")
    if set(cat.get("guarded_files", {})) != CAT_GUARDED_FILES:
        raise AssertionError("Змінився точний перелік успадкованих захищених файлів котика")
    for path, digest in CAT_PROTECTED_SHA256.items():
        protected = cat["protected_files"][path]
        if protected.get("sha256") != digest or protected.get("halloween_normalized_sha256") != digest:
            raise AssertionError(f"Integrity-варіант котика змінює захищений файл {path}")
    if cat["protected_files"]["app.js"].get("personal_theme_normalized_sha256") != "9d0d22989de0875719b8da48e76665c2ffd446cd5797110ef6d7ea8b79b5325c":
        raise AssertionError("Integrity-варіант котика змінив захист персональної теми app.js")
    if cat["protected_files"]["server.py"].get("personal_theme_normalized_sha256") != "0a88cd31457a5aea015d76b4df48caffbdd2c3f1af04072197c2bdddfb6e5b60":
        raise AssertionError("Integrity-варіант котика змінив захист персональної теми server.py")
    contracts.append(cat)
    contracts.append(load_nazk_contract(cat))
    for admin_path, expected_manifest_sha, expected_variant, expected_baseline in (
            (ADMIN_HISTORY_CONTRACT, ADMIN_HISTORY_CONTRACT_SHA256,
             "sandbox-admin-officer-link-v1", "de774010d99e3786eb6ff8308bba78aa5c9a6f13"),
            (ADMIN_CONTRACT, ADMIN_CONTRACT_SHA256,
             "sandbox-admin-officer-link-v2", "4625498cdb938f704cb8dc125c77bf58b2c2a7da")):
        raw = admin_path.read_bytes()
        if sha256(raw.replace(b"\r\n", b"\n")) != expected_manifest_sha:
            raise AssertionError("Змінено закріплений integrity-маніфест Admin officer link")
        admin = json.loads(raw.decode("utf-8"))
        expected_guards = (ADMIN_GUARDED_FILES if expected_variant == "sandbox-admin-officer-link-v2"
                           else set(admin.get("guarded_files", {})))
        if (admin.get("variant_id") != expected_variant or
                admin.get("baseline_sha") != expected_baseline or
                admin.get("hash_format") != ADMIN_HASH_FORMAT or
                set(admin.get("approved_scope", [])) != ADMIN_SCOPE or
                set(admin.get("product_files", {})) != ADMIN_PRODUCT_FILES or
                set(admin.get("guarded_files", {})) != expected_guards or
                set(admin.get("protected_files", {})) != ADMIN_PROTECTED_FILES):
            raise AssertionError("Admin integrity-варіант не відповідає повному погодженому маніфесту")
        for protected_path, expected in admin["protected_files"].items():
            if (expected.get("sha256") != expected.get("halloween_normalized_sha256") or
                    not expected.get("personal_theme_normalized_sha256")):
                raise AssertionError(f"Admin integrity-варіант недостатньо захищає {protected_path}")
        contracts.append(admin)
    delta_raw = ADMIN_V3_DELTA.read_bytes()
    if sha256(delta_raw.replace(b"\r\n", b"\n")) != ADMIN_V3_DELTA_SHA256:
        raise AssertionError("Змінено закріплений integrity-addendum Admin v3")
    delta = json.loads(delta_raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_files_additional",
                       "product_overrides", "protected_overrides", "remove_from_guarded_files", "remove_from_protected_files",
                       "guarded_overrides"} or
            delta.get("variant_id") != "sandbox-admin-officer-link-v3" or
            delta.get("baseline_sha") != "4625498cdb938f704cb8dc125c77bf58b2c2a7da" or
            delta.get("base_manifest") != ADMIN_CONTRACT.name or
            delta.get("base_manifest_sha256") != ADMIN_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != {
                "close_reference_directory_sqlite_connections",
                "close_winner_snapshot_sqlite_connections",
                "release_test_fixture_sqlite_connections",
                "ascii_safe_amcu_worker_json",
                "stable_local_http_fixture_teardown",
            } or
            set(delta.get("product_files_additional", {})) != {"reference_directories.py"} or
            delta.get("product_files_additional", {}).get("reference_directories.py", {}).get("sha256") !=
                "8b893ae98a514e698145bcd6285787a115c045f1eb8afd716468cc5e9f50fe7a" or
            set(delta.get("product_overrides", {})) != {"server.py"} or
            delta.get("product_overrides", {}).get("server.py", {}).get("sha256") !=
                "1fff8455afa5adb9a59c76941d4b32cb7b14252672ac4361325d1a211ea5ce58" or
            delta.get("protected_overrides", {}).get("server.py", {}).get("sha256") !=
                "1fff8455afa5adb9a59c76941d4b32cb7b14252672ac4361325d1a211ea5ce58" or
            delta.get("protected_overrides", {}).get("server.py", {}).get("halloween_normalized_sha256") !=
                "1fff8455afa5adb9a59c76941d4b32cb7b14252672ac4361325d1a211ea5ce58" or
            delta.get("protected_overrides", {}).get("server.py", {}).get("personal_theme_normalized_sha256") !=
                "f3e4311b965e73fb97383d557e7c1b52007991d56329412ff9bb3d458bc1b598" or
            set(delta.get("remove_from_guarded_files", [])) != {"reference_directories.py"} or
            delta.get("remove_from_protected_files", []) != [] or
            set(delta.get("guarded_overrides", {})) != {
                "test_sandbox_nazk_columns_integrity.py",
                "test_supplier_filter_excel.py",
                "validation/local_release_20260911/test_amcu_open_data.py",
                "validation/local_release_20260911/test_amcu_refresh_recovery.py",
                "validation/local_release_20260911/test_winner_decisions.py",
                "validation/local_release_20260911/test_sandbox_operational_phase1.py",
                "validation/local_release_20260911/test_bids_runtime.py",
                "validation/local_release_20260911/test_admin_officer_linkage.py",
            } or
            delta.get("guarded_overrides", {}).get("test_sandbox_nazk_columns_integrity.py", {}).get("sha256") !=
                "045b5d72f0514dc5e9b0e89fdc3e84d7815409ca1ff51fc4b019940a0ef1aa71" or
            delta.get("guarded_overrides", {}).get("test_supplier_filter_excel.py", {}).get("sha256") !=
                "86ee2cf0209e3b4637c13204164499ba66fb9a543ed9c515f5f758a6c84d7ddd" or
            delta.get("guarded_overrides", {}).get("validation/local_release_20260911/test_amcu_open_data.py", {}).get("sha256") !=
                "807edfe3d88824ae2b72d52e428e07c5f053b042224e0ac976308f58b8983353" or
            delta.get("guarded_overrides", {}).get("validation/local_release_20260911/test_amcu_refresh_recovery.py", {}).get("sha256") !=
                "66ddf583b0160128ddb2ceeb074c91c037ff790685cbaae20c07d2d4f5ee06c6" or
            delta.get("guarded_overrides", {}).get("validation/local_release_20260911/test_winner_decisions.py", {}).get("sha256") !=
                "bd744e729fa6d60b589d3479e47a74d64cda94af71d1f23598b6bb79e79d053b" or
            delta.get("guarded_overrides", {}).get("validation/local_release_20260911/test_sandbox_operational_phase1.py", {}).get("sha256") !=
                "69fbacdcbaaf32dd04657dd8428eac97a6856fde5c9c8697aca747e05a099183" or
            delta.get("guarded_overrides", {}).get("validation/local_release_20260911/test_bids_runtime.py", {}).get("sha256") !=
                "f36145967a52d19632a845ca4206562429e7a5f2f6c0a4be4da6b40b19f6195d" or
            delta.get("guarded_overrides", {}).get("validation/local_release_20260911/test_admin_officer_linkage.py", {}).get("sha256") !=
                "eef9cf905325fd223c4288ea3c36bd24c6765551d50d1b785bca16c0e3b88bbe"):
        raise AssertionError("Admin integrity-addendum v3 має неочікуваний scope")
    v2 = next(contract for contract in contracts if contract.get("variant_id") == "sandbox-admin-officer-link-v2")
    v3 = copy.deepcopy(v2)
    v3["variant_id"] = delta["variant_id"]
    v3["approved_scope"] = sorted(set(v3["approved_scope"]) | set(delta["approved_scope_additions"]))
    v3["product_files"].update(delta["product_files_additional"])
    v3["product_files"].update(delta["product_overrides"])
    for guarded_path in delta["remove_from_guarded_files"]:
        del v3["guarded_files"][guarded_path]
    for protected_path in delta["remove_from_protected_files"]:
        del v3["protected_files"][protected_path]
    v3["protected_files"].update(delta["protected_overrides"])
    v3["guarded_files"].update(delta["guarded_overrides"])
    contracts.append(v3)
    ui_v1 = load_ui_candidate_v1(v3)
    contracts.append(ui_v1)
    ui_v2 = load_ui_candidate_v2(ui_v1)
    contracts.append(ui_v2)
    ui_v3 = load_ui_candidate_v3(ui_v2)
    contracts.append(ui_v3)
    ui_v4 = load_ui_candidate_v4(ui_v3)
    contracts.append(ui_v4)
    ui_v5 = load_ui_candidate_v5(ui_v4)
    contracts.append(ui_v5)
    ui_v6 = load_ui_candidate_v6(ui_v5)
    contracts.append(ui_v6)
    ui_v7 = load_ui_candidate_v7(ui_v6)
    contracts.append(ui_v7)
    ui_v8 = load_ui_candidate_v8(ui_v7)
    contracts.append(ui_v8)
    ui_v9 = load_ui_candidate_v9(ui_v8)
    contracts.append(ui_v9)
    ui_v10 = load_ui_candidate_v10(ui_v9)
    contracts.append(ui_v10)
    ui_v11 = load_ui_candidate_v11(ui_v10)
    contracts.append(ui_v11)
    ui_v12 = load_ui_candidate_v12(ui_v11)
    contracts.append(ui_v12)
    preview = load_nazk_preview_contract(ui_v11)
    contracts.append(preview)
    integrated = load_nazk_appeals_integrated_contract(ui_v12, preview)
    contracts.append(integrated)
    scroll = load_nazk_scroll_contract(integrated)
    contracts.append(scroll)
    appeals_api = load_appeals_scenario_api_contract(integrated)
    contracts.append(appeals_api)
    stabilization_v1 = load_stabilization_contract(scroll, appeals_api)
    contracts.append(stabilization_v1)
    stabilization_v2 = load_stabilization_v2_contract(stabilization_v1)
    contracts.append(stabilization_v2)
    stabilization_v3 = load_stabilization_v3_contract(stabilization_v2)
    contracts.append(stabilization_v3)
    contracts.append(load_stabilization_v4_contract(stabilization_v3))
    return contracts


def load_ui_candidate_v1(admin_v3):
    raw = UI_CANDIDATE_DELTA.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != UI_CANDIDATE_DELTA_SHA256:
        raise AssertionError("Changed pinned integrated Sandbox UI integrity addendum")
    delta = json.loads(raw.decode("utf-8"))
    expected_guards = ((set(admin_v3["guarded_files"]) - UI_CANDIDATE_PRODUCTS) |
                       UI_CANDIDATE_GUARDS)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_files",
                       "protected_files", "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_ID or
            delta.get("baseline_sha") != "d457aae211bc0b88cdc66414b9e5765ac7ba350d" or
            delta.get("base_manifest") != "test_sandbox_admin_officer_link_integrity_v3.json" or
            delta.get("base_manifest_sha256") != ADMIN_V3_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_SCOPE or
            set(delta.get("product_files", {})) != UI_CANDIDATE_PRODUCTS or
            set(delta.get("protected_files", {})) != ADMIN_PROTECTED_FILES or
            set(delta.get("guarded_overrides", {})) != expected_guards):
        raise AssertionError("Integrated Sandbox UI integrity addendum has an unexpected exact scope")
    candidate = copy.deepcopy(admin_v3)
    candidate["variant_id"] = UI_CANDIDATE_ID
    candidate["baseline_sha"] = delta["baseline_sha"]
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                         set(delta["approved_scope_additions"]))
    candidate["product_files"] = delta["product_files"]
    candidate["protected_files"] = delta["protected_files"]
    candidate["guarded_files"] = delta["guarded_overrides"]
    return candidate


def load_ui_candidate_v2(ui_v1):
    raw = UI_CANDIDATE_V2_DELTA.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != UI_CANDIDATE_V2_DELTA_SHA256:
        raise AssertionError("Changed pinned integrated Sandbox UI v2 addendum")
    delta = json.loads(raw.decode("utf-8"))
    expected_remove = UI_CANDIDATE_V2_REMOVE_GUARDS
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_files_additional",
                       "product_overrides", "protected_overrides", "remove_from_guarded_files",
                       "remove_from_protected_files", "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V2_ID or
            delta.get("baseline_sha") != "d457aae211bc0b88cdc66414b9e5765ac7ba350d" or
            delta.get("base_manifest") != UI_CANDIDATE_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V2_SCOPE or
            set(delta.get("product_files_additional", {})) != UI_CANDIDATE_V2_PRODUCT_ADDITIONS or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V2_PRODUCT_OVERRIDES or
            set(delta.get("protected_overrides", {})) != ADMIN_PROTECTED_FILES or
            set(delta.get("remove_from_guarded_files", [])) != expected_remove or
            delta.get("remove_from_protected_files") != [] or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V2_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v2 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v1)
    candidate["variant_id"] = UI_CANDIDATE_V2_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                          set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_files_additional"])
    candidate["product_files"].update(delta["product_overrides"])
    for guarded_path in delta["remove_from_guarded_files"]:
        if guarded_path not in candidate["guarded_files"]:
            raise AssertionError(f"Expected promoted UI test file is not guarded: {guarded_path}")
        del candidate["guarded_files"][guarded_path]
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate


def load_ui_candidate_v3(ui_v2):
    raw = UI_CANDIDATE_V3_DELTA.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != UI_CANDIDATE_V3_DELTA_SHA256:
        raise AssertionError("Changed pinned integrated Sandbox UI v3 addendum")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "remove_from_guarded_files",
                       "product_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V3_ID or
            delta.get("baseline_sha") != "d457aae211bc0b88cdc66414b9e5765ac7ba350d" or
            delta.get("base_manifest") != UI_CANDIDATE_V2_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V2_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V3_SCOPE or
            set(delta.get("remove_from_guarded_files", [])) != {"test_sandbox_admin_officer_link_integrity.py"} or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V3_PRODUCT_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v3 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v2)
    candidate["variant_id"] = UI_CANDIDATE_V3_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                          set(delta["approved_scope_additions"]))
    for guarded_path in delta["remove_from_guarded_files"]:
        if guarded_path not in candidate["guarded_files"]:
            raise AssertionError(f"Expected promoted v3 test file is not guarded: {guarded_path}")
        del candidate["guarded_files"][guarded_path]
    candidate["product_files"].update(delta["product_overrides"])
    return candidate


def load_ui_candidate_v4(ui_v3):
    raw = UI_CANDIDATE_V4_DELTA.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != UI_CANDIDATE_V4_DELTA_SHA256:
        raise AssertionError("Changed pinned integrated Sandbox UI v4 addendum")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V4_ID or
            delta.get("baseline_sha") != "d457aae211bc0b88cdc66414b9e5765ac7ba350d" or
            delta.get("base_manifest") != UI_CANDIDATE_V3_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V3_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V4_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V4_PRODUCT_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v4 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v3)
    candidate["variant_id"] = UI_CANDIDATE_V4_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                          set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    return candidate


def load_ui_candidate_v5(ui_v4):
    raw = UI_CANDIDATE_V5_DELTA.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != UI_CANDIDATE_V5_DELTA_SHA256:
        raise AssertionError("Changed integrated Sandbox UI v5 integrity addendum")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V5_ID or
            delta.get("baseline_sha") != "d457aae211bc0b88cdc66414b9e5765ac7ba350d" or
            delta.get("base_manifest") != UI_CANDIDATE_V4_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V4_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V5_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V5_PRODUCT_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v5 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v4)
    candidate["variant_id"] = UI_CANDIDATE_V5_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                          set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    return candidate



def _load_ui_delta(path, expected_sha):
    raw = path.read_bytes()
    if sha256(raw.replace(b"\r\n", b"\n")) != expected_sha:
        raise AssertionError(f"Changed pinned integrated Sandbox UI addendum: {path.name}")
    return json.loads(raw.decode("utf-8"))


def load_ui_candidate_v6(ui_v5):
    delta = _load_ui_delta(UI_CANDIDATE_V6_DELTA, UI_CANDIDATE_V6_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "protected_overrides", "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V6_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V5_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V5_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V6_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V6_PRODUCT_OVERRIDES or
            set(delta.get("protected_overrides", {})) != UI_CANDIDATE_V6_PROTECTED_OVERRIDES or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V6_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v6 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v5)
    candidate["variant_id"] = UI_CANDIDATE_V6_ID
    candidate["baseline_sha"] = delta["baseline_sha"]
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate


def load_ui_candidate_v7(ui_v6):
    delta = _load_ui_delta(UI_CANDIDATE_V7_DELTA, UI_CANDIDATE_V7_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "protected_overrides", "remove_from_guarded_files", "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V7_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V6_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V6_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V7_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V7_PRODUCT_OVERRIDES or
            set(delta.get("protected_overrides", {})) != UI_CANDIDATE_V7_PROTECTED_OVERRIDES or
            set(delta.get("remove_from_guarded_files", [])) != {"protocol_supplier_names.py"} or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V7_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v7 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v6)
    candidate["variant_id"] = UI_CANDIDATE_V7_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["protected_files"].update(delta["protected_overrides"])
    for path in delta["remove_from_guarded_files"]:
        if path not in candidate["guarded_files"]:
            raise AssertionError(f"Expected promoted v7 test file is not guarded: {path}")
        del candidate["guarded_files"][path]
    candidate["guarded_files"].update(delta["guarded_overrides"])
    for path, expected in delta["protected_overrides"].items():
        if (expected.get("sha256") != expected.get("halloween_normalized_sha256") or
                not expected.get("personal_theme_normalized_sha256")):
            raise AssertionError(f"Integrated Sandbox UI v7 does not preserve protected projections: {path}")
    return candidate


def load_ui_candidate_v8(ui_v7):
    delta = _load_ui_delta(UI_CANDIDATE_V8_DELTA, UI_CANDIDATE_V8_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "protected_overrides", "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V8_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V7_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V7_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V8_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V8_PRODUCT_OVERRIDES or
            set(delta.get("protected_overrides", {})) != UI_CANDIDATE_V8_PROTECTED_OVERRIDES or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V8_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v8 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v7)
    candidate["variant_id"] = UI_CANDIDATE_V8_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    for path, expected in delta["protected_overrides"].items():
        if (expected.get("sha256") != expected.get("halloween_normalized_sha256") or
                not expected.get("personal_theme_normalized_sha256")):
            raise AssertionError(f"Integrated Sandbox UI v8 does not preserve protected projections: {path}")
    return candidate


def load_ui_candidate_v9(ui_v8):
    delta = _load_ui_delta(UI_CANDIDATE_V9_DELTA, UI_CANDIDATE_V9_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V9_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V8_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V8_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V9_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V9_PRODUCT_OVERRIDES or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V9_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v9 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v8)
    candidate["variant_id"] = UI_CANDIDATE_V9_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate


def load_ui_candidate_v10(ui_v9):
    delta = _load_ui_delta(UI_CANDIDATE_V10_DELTA, UI_CANDIDATE_V10_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V10_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V9_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V9_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V10_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V10_PRODUCT_OVERRIDES or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V10_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v10 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v9)
    candidate["variant_id"] = UI_CANDIDATE_V10_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate


def load_ui_candidate_v11(ui_v10):
    delta = _load_ui_delta(UI_CANDIDATE_V11_DELTA, UI_CANDIDATE_V11_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V11_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V10_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V10_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V11_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V11_PRODUCT_OVERRIDES or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V11_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v11 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v10)
    candidate["variant_id"] = UI_CANDIDATE_V11_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate

def load_ui_candidate_v12(ui_v11):
    delta = _load_ui_delta(UI_CANDIDATE_V12_DELTA, UI_CANDIDATE_V12_DELTA_SHA256)
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "protected_overrides", "guarded_overrides"} or
            delta.get("variant_id") != UI_CANDIDATE_V12_ID or
            delta.get("baseline_sha") != "3fc2b2977073f56c570941fbcdff49b1a187fb7e" or
            delta.get("base_manifest") != UI_CANDIDATE_V11_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V11_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != UI_CANDIDATE_V12_SCOPE or
            set(delta.get("product_overrides", {})) != UI_CANDIDATE_V12_PRODUCT_OVERRIDES or
            set(delta.get("protected_overrides", {})) != UI_CANDIDATE_V12_PROTECTED_OVERRIDES or
            set(delta.get("guarded_overrides", {})) != UI_CANDIDATE_V12_GUARD_OVERRIDES):
        raise AssertionError("Integrated Sandbox UI v12 addendum has an unexpected exact scope")
    candidate = copy.deepcopy(ui_v11)
    candidate["variant_id"] = UI_CANDIDATE_V12_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate

def sha256(data):
    return hashlib.sha256(data).hexdigest()


def canonical_content(relative, content):
    """Normalize checkout line endings, but never normalize binary templates."""
    if not relative.endswith((".docx", ".webp", ".png", ".jpg", ".jpeg", ".gif", ".zip")):
        return content.replace(b"\r\n", b"\n")
    return content


def manifest_tree_matches(contract, root=ROOT):
    """Check every pinned file in one manifest against an arbitrary read-only tree."""
    if contract not in load_contracts():
        return False  # A partial or caller-supplied manifest is never an exception.
    for section in ("product_files", "guarded_files", "protected_files"):
        for relative, expected in contract.get(section, {}).items():
            try:
                content = (Path(root) / relative).read_bytes()
            except OSError:
                return False
            expected_sha = expected.get("sha256")
            if expected_sha is None:
                continue
            if sha256(canonical_content(relative, content)) != expected_sha:
                return False
    return True


def exact_variant_file_matches(path, content):
    """Accept only bytes belonging to one currently exact, complete variant."""
    relative = str(path).replace("\\", "/")
    digest = sha256(canonical_content(relative, content))
    for contract in load_contracts():
        expected = contract.get("product_files", {}).get(relative)
        if expected is None:
            expected = contract.get("guarded_files", {}).get(relative)
        if expected is None:
            expected = contract.get("protected_files", {}).get(relative)
        if expected and digest == expected["sha256"] and manifest_tree_matches(contract):
            return True
    return False


def exact_variant_tree_matches():
    """Require a complete exact match to one prior or newly approved variant."""
    return any(manifest_tree_matches(contract) for contract in load_contracts())


def protected_content_matches(path, content, actual_projection_sha256,
                              baseline_projection_sha256, projection_name):
    """Accept the immutable baseline digest or the complete pinned variant."""
    if actual_projection_sha256 == baseline_projection_sha256:
        return True
    if path not in PROTECTED_FILES or not exact_variant_file_matches(path, content):
        return False
    if not exact_variant_tree_matches():
        return False
    for contract in load_contracts():
        if not manifest_tree_matches(contract):
            continue
        expected = contract["protected_files"].get(path, {}).get(projection_name)
        if expected and expected == actual_projection_sha256:
            return True
    return False


# Additive, exact read-only NAZK preview. Every previous manifest remains pinned.
PREVIEW_CONTRACT = ROOT / "test_sandbox_nazk_preview_integrity_variant.json"
PREVIEW_CONTRACT_SHA256 = "71b8ae89a87099061f72427b759829fd8129a05f976d5fa5a4678dcbf1e17b15"
PREVIEW_VARIANT_ID = "sandbox-nazk-readonly-preview-appeals-v1"
PREVIEW_BASELINE = "f394d4c5e5f7afd76f39985d54e3e157ae65c811"
PREVIEW_SCOPE = {
    "read-only-supplier-nazk-preview-in-operational-tasks",
    "reuse-canonical-history-coverage-and-activity",
    "role-scoped-minimized-preview-without-domain-writes",
    "preserve-dom-stability-column-preferences-and-existing-task-handlers",
}
PREVIEW_EXTRA_GUARDS = {"operational_tasks.py", "nazk_workflow.py", "nazk_evidence.py",
                        "supplier_activity.py", "registry_popovers.js", "scheduler_runtime.py"}
PREVIEW_PRODUCTS = {
    "server.py", "index.html", "nazk_preview.py", "nazk_preview.js", "nazk_preview.css",
    "test_sandbox_admin_officer_link_integrity.py", "test_sandbox_nazk_columns_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py", "test_sandbox_nazk_preview_integrity.py",
    "validation/nazk_preview_fixture.py", "validation/nazk_preview_browser_fixture.py",
    "validation/nazk_preview_browser.cjs", "validation/local_release_20260911/test_nazk_preview.py",
    "validation/fixtures/nazk_preview_baseline_f394d4c.zip", "validation/run_local_release.py",
}

INTEGRATED_CONTRACT = ROOT / "test_sandbox_nazk_appeals_integrated_v1.json"
INTEGRATED_CONTRACT_SHA256 = "0cb672a1d10e55562a2672a36c4089cd657bc62cba7499ffa42ecc15d3eaa3e2"
INTEGRATED_CONTRACT_FORMATTED_SHA256 = "68660572b26e3e4a5cb1d4de928a3edb7ede9689bf19a238888dbe6a7b84fd7e"
INTEGRATED_VARIANT_ID = "sandbox-nazk-appeals-integrated-v1"
INTEGRATED_SCOPE = {"combine-read-only-nazk-preview-and-appeals-scenario-fix"}
INTEGRATED_PRODUCTS = (UI_CANDIDATE_V12_PRODUCT_OVERRIDES | PREVIEW_PRODUCTS |
                       {"validation/fixtures/appeals_scenario_v11_tail.zip"})
INTEGRATED_PROTECTED = UI_CANDIDATE_V12_PROTECTED_OVERRIDES | {"server.py"}
INTEGRATED_GUARDS = UI_CANDIDATE_V12_GUARD_OVERRIDES | PREVIEW_EXTRA_GUARDS | PREVIEW_PRODUCTS.intersection(
    {"test_sandbox_admin_officer_link_integrity.py", "test_sandbox_nazk_columns_integrity.py",
     "validation/run_local_release.py"})
APPEALS_API_CONTRACT = ROOT / "test_sandbox_appeals_scenario_api_integrity_v1.json"
APPEALS_API_CONTRACT_SHA256 = "6a145080f048c656217a22e01714226d1b8e28d3d3a206113d43e07b2181d628"
APPEALS_API_VARIANT_ID = "sandbox-appeals-scenario-api-v1"
APPEALS_API_BASELINE = "fc719b07f7ce6bd43fcdf9815795f0f2906901e8"
APPEALS_API_SCOPE = {
    "appeals-list-projects-only-exact-saved-card-scenario-snapshot",
    "appeals-list-never-fetches-prozorro-tender-data",
    "appeals-list-leaves-scenario-empty-for-missing-or-partial-snapshots",
    "appeals-list-preserves-saved-read-only-justification-separately",
}
APPEALS_API_PRODUCT_OVERRIDES = {
    "server.py", "validation/appeals_justification_browser.cjs",
    "validation/run_local_release.py",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "test_sandbox_nazk_preview_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
APPEALS_API_PRODUCT_ADDITIONS = {
    "validation/local_release_20260911/test_violation_reports.py",
    "validation/fixtures/appeals_scenario_v11_api_tail.zip",
}
APPEALS_API_GUARD_OVERRIDES = {
    "validation/run_local_release.py",
    "validation/appeals_justification_browser.cjs",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "validation/local_release_20260911/test_violation_reports.py",
}

SCROLL_CONTRACT = ROOT / "test_sandbox_nazk_scroll_integrity_variant.json"
SCROLL_CONTRACT_SHA256 = "2ee78bdf953d575d97dfc32e94b8ed8664328ac9e57d7b7a4fea818ac08c83a8"
SCROLL_VARIANT_ID = "sandbox-nazk-scroll-v1"
SCROLL_BASELINE = "fc719b07f7ce6bd43fcdf9815795f0f2906901e8"
SCROLL_SCOPE = {
    "restore-bounded-vertical-scroll-to-last-nazk-row",
    "preserve-sticky-header-and-horizontal-overflow",
    "compact-preview-toolbar-and-remove-duplicate-read-only-notice",
}
SCROLL_PRODUCTS = {
    "nazk_preview.css", "nazk_preview.js", "validation/nazk_preview_browser.cjs",
    "validation/nazk_preview_scroll_browser.cjs", "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py", "test_sandbox_nazk_preview_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py", "test_sandbox_nazk_scroll_integrity.py",
}

STABILIZATION_CONTRACT = ROOT / "test_sandbox_nazk_appeals_stabilization_v1.json"
STABILIZATION_CONTRACT_SHA256 = "9233e8d9a27adf855d22a8cc3a5e2f7dc167ba86dac6c02fc3451ffa92d6f8c7"
STABILIZATION_V1_VARIANT_ID = "sandbox-nazk-appeals-stabilization-v1"
STABILIZATION_V2_CONTRACT = ROOT / "test_sandbox_nazk_appeals_stabilization_v2.json"
STABILIZATION_V2_CONTRACT_SHA256 = "61512ea36622fd1173704c5123212471d4830831798af9be6595514cb381014c"
STABILIZATION_V2_VARIANT_ID = "sandbox-nazk-appeals-stabilization-v2"
STABILIZATION_V3_CONTRACT = ROOT / "test_sandbox_nazk_appeals_stabilization_v3.json"
STABILIZATION_V3_CONTRACT_SHA256 = "3b90b40c6474c1be098c00e345b996ad4b9313359d59fc4c88c54ac440877c15"
STABILIZATION_V3_VARIANT_ID = "sandbox-nazk-appeals-stabilization-v3"
STABILIZATION_V4_CONTRACT = ROOT / "test_sandbox_nazk_appeals_stabilization_v4.json"
STABILIZATION_V4_CONTRACT_SHA256 = "edd13c837362a456a6e026366d003b86d81df96cb6d26e91a6d184245fb46828"
STABILIZATION_VARIANT_ID = "sandbox-nazk-appeals-stabilization-v4"
STABILIZATION_SCOPE = {"combine-verified-nazk-scroll-and-bounded-appeals-scenario-api"}
STABILIZATION_PRODUCT_OVERRIDES = {
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_nazk_columns_integrity.py",
    "test_sandbox_nazk_preview_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
    "test_sandbox_nazk_scroll_integrity.py",
    "test_sandbox_appeals_scenario_api_integrity.py",
}
STABILIZATION_PRODUCT_ADDITIONS = {
    "test_sandbox_nazk_appeals_stabilization_integrity.py",
}
STABILIZATION_V2_SCOPE = {
    "show-valid-saved-scenario-snapshot-for-editable-appeals",
    "strip-leading-scenario-label-in-table-only",
    "show-justification-viewer-only-for-nonempty-saved-text",
}
STABILIZATION_V2_PRODUCT_OVERRIDES = {
    "app.js",
    "server.py",
    "validation/appeals_justification_browser.cjs",
    "test_sandbox_appeals_scenario_api_integrity.py",
    "test_sandbox_nazk_appeals_stabilization_integrity.py",
    "test_sandbox_nazk_preview_integrity.py",
    "test_sandbox_nazk_scroll_integrity.py",
    "validation/local_release_20260911/test_violation_reports.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
STABILIZATION_V2_PRODUCT_ADDITIONS = {
    "test_sandbox_appeals_scenario_readonly_integrity.py",
}
STABILIZATION_V3_SCOPE = {
    "cache-minimal-current-scenario-context-separately-from-decision-snapshot",
    "reuse-card-fetched-prozorro-context-for-list-without-network-calls",
    "validate-report-reason-version-freshness-and-input-fingerprint",
    "prevent-older-or-concurrent-context-from-overwriting-newer-snapshot",
}
STABILIZATION_V3_PRODUCT_OVERRIDES = {
    "server.py",
    "validation/local_release_20260911/test_violation_reports.py",
    "validation/appeals_justification_browser.cjs",
    "test_sandbox_appeals_scenario_api_integrity.py",
    "test_sandbox_appeals_scenario_readonly_integrity.py",
    "test_sandbox_nazk_appeals_stabilization_integrity.py",
    "test_sandbox_nazk_preview_integrity.py",
    "test_sandbox_nazk_scroll_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
STABILIZATION_V3_PRODUCT_ADDITIONS = {
    "test_sandbox_nazk_appeals_stabilization_v3_integrity.py",
}
STABILIZATION_V4_SCOPE = {
    "render-full-appeals-scenario-with-natural-wrapping-at-configured-column-width",
    "allow-appeals-scenario-row-height-to-grow-without-clipping",
    "link-appeal-card-to-exact-zakupivli-pro-platform-id",
    "map-technical-appeal-statuses-to-ukrainian-labels",
    "increase-supplier-warning-counter-heading-gap",
}
STABILIZATION_V4_PRODUCT_OVERRIDES = {
    "app.js",
    "styles.css",
    "validation/appeals_justification_browser.cjs",
    "validation/table_widths_unified_browser.cjs",
    "validation/run_local_release.py",
    "test_sandbox_admin_officer_link_integrity.py",
    "test_sandbox_appeals_scenario_api_integrity.py",
    "test_sandbox_appeals_scenario_readonly_integrity.py",
    "test_sandbox_nazk_appeals_stabilization_integrity.py",
    "test_sandbox_nazk_appeals_stabilization_v3_integrity.py",
    "test_sandbox_nazk_preview_integrity.py",
    "test_sandbox_nazk_scroll_integrity.py",
    "test_sandbox_ui_integrated_d457_integrity.py",
}
STABILIZATION_V4_PRODUCT_ADDITIONS = {
    "test_sandbox_nazk_appeals_stabilization_v4_integrity.py",
    "validation/fixtures/table_widths_v11_tail.zip",
}


def load_nazk_preview_contract(previous):
    raw = PREVIEW_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != PREVIEW_CONTRACT_SHA256:
        raise AssertionError("Changed exact NAZK preview contract")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides", "guarded_additions"} or
            delta.get("variant_id") != PREVIEW_VARIANT_ID or delta.get("baseline_sha") != PREVIEW_BASELINE or
            delta.get("base_manifest") != UI_CANDIDATE_V11_DELTA.name or
            delta.get("base_manifest_sha256") != UI_CANDIDATE_V11_DELTA_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != PREVIEW_SCOPE or
            set(delta.get("product_overrides", {})) != PREVIEW_PRODUCTS or
            set(delta.get("guarded_additions", {})) != PREVIEW_EXTRA_GUARDS or
            previous.get("variant_id") != UI_CANDIDATE_V11_ID):
        raise AssertionError("Unexpected exact NAZK preview scope")
    candidate = copy.deepcopy(previous)
    candidate["variant_id"] = PREVIEW_VARIANT_ID
    candidate["baseline_sha"] = PREVIEW_BASELINE
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | PREVIEW_SCOPE)
    candidate["product_files"].update(delta["product_overrides"])
    candidate["guarded_files"].update(delta["guarded_additions"])
    for section in ("protected_files", "guarded_files"):
        for relative in set(candidate[section]) & PREVIEW_PRODUCTS:
            candidate[section][relative] = delta["product_overrides"][relative]
    return candidate


def load_nazk_appeals_integrated_contract(scenario, preview):
    raw = INTEGRATED_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) not in {INTEGRATED_CONTRACT_SHA256, INTEGRATED_CONTRACT_FORMATTED_SHA256}:
        raise AssertionError("Changed exact combined NAZK/Appeals contract")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "scenario_manifest", "scenario_manifest_sha256",
                       "preview_manifest", "preview_manifest_sha256", "hash_format",
                       "approved_scope_additions", "product_overrides", "protected_overrides",
                       "guarded_overrides"} or
            delta.get("variant_id") != INTEGRATED_VARIANT_ID or
            delta.get("baseline_sha") != PREVIEW_BASELINE or
            delta.get("scenario_manifest") != UI_CANDIDATE_V12_DELTA.name or
            delta.get("scenario_manifest_sha256") != UI_CANDIDATE_V12_DELTA_SHA256 or
            delta.get("preview_manifest") != PREVIEW_CONTRACT.name or
            delta.get("preview_manifest_sha256") != PREVIEW_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != INTEGRATED_SCOPE or
            set(delta.get("product_overrides", {})) != INTEGRATED_PRODUCTS or
            set(delta.get("protected_overrides", {})) != INTEGRATED_PROTECTED or
            set(delta.get("guarded_overrides", {})) != INTEGRATED_GUARDS or
            scenario.get("variant_id") != UI_CANDIDATE_V12_ID or
            preview.get("variant_id") != PREVIEW_VARIANT_ID):
        raise AssertionError("Combined NAZK/Appeals contract has an unexpected exact scope")
    candidate = copy.deepcopy(preview)
    candidate["variant_id"] = INTEGRATED_VARIANT_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                         set(scenario["approved_scope"]) |
                                         set(delta["approved_scope_additions"]))
    candidate["product_files"].update(scenario["product_files"])
    candidate["product_files"].update(delta["product_overrides"])
    candidate["protected_files"].update(scenario["protected_files"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(scenario["guarded_files"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate


def load_appeals_scenario_api_contract(integrated):
    raw = APPEALS_API_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != APPEALS_API_CONTRACT_SHA256:
        raise AssertionError("Changed exact Appeals scenario API contract")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "product_files_additional", "protected_server_overrides", "guarded_overrides"} or
            delta.get("variant_id") != APPEALS_API_VARIANT_ID or
            delta.get("baseline_sha") != APPEALS_API_BASELINE or
            delta.get("base_manifest") != INTEGRATED_CONTRACT.name or
            delta.get("base_manifest_sha256") != INTEGRATED_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != APPEALS_API_SCOPE or
            set(delta.get("product_overrides", {})) != APPEALS_API_PRODUCT_OVERRIDES or
            set(delta.get("product_files_additional", {})) != APPEALS_API_PRODUCT_ADDITIONS or
            set(delta.get("protected_server_overrides", {})) != {"halloween_normalized_sha256",
                                                                  "personal_theme_normalized_sha256"} or
            set(delta.get("guarded_overrides", {})) != APPEALS_API_GUARD_OVERRIDES or
            integrated.get("variant_id") != INTEGRATED_VARIANT_ID):
        raise AssertionError("Appeals scenario API contract has an unexpected exact scope")
    candidate = copy.deepcopy(integrated)
    candidate["variant_id"] = APPEALS_API_VARIANT_ID
    candidate["baseline_sha"] = APPEALS_API_BASELINE
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                         set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["product_files"].update(delta["product_files_additional"])
    candidate["protected_files"]["server.py"] = delta["product_overrides"]["server.py"]
    candidate["protected_files"]["server.py"].update(delta["protected_server_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    return candidate


def load_nazk_scroll_contract(integrated):
    raw = SCROLL_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != SCROLL_CONTRACT_SHA256:
        raise AssertionError("Changed exact NAZK scroll integrity contract")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides"} or
            delta.get("variant_id") != SCROLL_VARIANT_ID or
            delta.get("baseline_sha") != SCROLL_BASELINE or
            delta.get("base_manifest") != INTEGRATED_CONTRACT.name or
            delta.get("base_manifest_sha256") != INTEGRATED_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != SCROLL_SCOPE or
            set(delta.get("product_overrides", {})) != SCROLL_PRODUCTS or
            integrated.get("variant_id") != INTEGRATED_VARIANT_ID):
        raise AssertionError("Unexpected exact NAZK scroll scope")
    candidate = copy.deepcopy(integrated)
    candidate["variant_id"] = SCROLL_VARIANT_ID
    candidate["baseline_sha"] = SCROLL_BASELINE
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) | SCROLL_SCOPE)
    candidate["product_files"].update(delta["product_overrides"])
    for section in ("protected_files", "guarded_files"):
        for relative in set(candidate[section]) & SCROLL_PRODUCTS:
            candidate[section][relative] = delta["product_overrides"][relative]
    return candidate


def load_stabilization_contract(scroll, appeals_api):
    raw = STABILIZATION_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != STABILIZATION_CONTRACT_SHA256:
        raise AssertionError("Changed exact combined stabilization integrity contract")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "scroll_manifest", "scroll_manifest_sha256",
                       "appeals_manifest", "appeals_manifest_sha256", "hash_format",
                       "approved_scope_additions", "product_overrides", "product_files_additional",
                       "guarded_overrides", "guarded_additions"} or
            delta.get("variant_id") != STABILIZATION_V1_VARIANT_ID or
            delta.get("baseline_sha") != SCROLL_BASELINE or
            delta.get("scroll_manifest") != SCROLL_CONTRACT.name or
            delta.get("scroll_manifest_sha256") != SCROLL_CONTRACT_SHA256 or
            delta.get("appeals_manifest") != APPEALS_API_CONTRACT.name or
            delta.get("appeals_manifest_sha256") != APPEALS_API_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != STABILIZATION_SCOPE or
            set(delta.get("product_overrides", {})) != STABILIZATION_PRODUCT_OVERRIDES or
            set(delta.get("product_files_additional", {})) != STABILIZATION_PRODUCT_ADDITIONS or
            set(delta.get("guarded_overrides", {})) != STABILIZATION_PRODUCT_OVERRIDES or
            set(delta.get("guarded_additions", {})) != STABILIZATION_PRODUCT_ADDITIONS or
            scroll.get("variant_id") != SCROLL_VARIANT_ID or
            appeals_api.get("variant_id") != APPEALS_API_VARIANT_ID):
        raise AssertionError("Combined stabilization contract has an unexpected exact scope")
    candidate = copy.deepcopy(scroll)
    candidate["variant_id"] = STABILIZATION_V1_VARIANT_ID
    candidate["baseline_sha"] = SCROLL_BASELINE
    candidate["approved_scope"] = sorted(
        set(candidate["approved_scope"]) | set(appeals_api["approved_scope"]) |
        set(delta["approved_scope_additions"]))
    for relative in APPEALS_API_PRODUCT_OVERRIDES | APPEALS_API_PRODUCT_ADDITIONS:
        candidate["product_files"][relative] = appeals_api["product_files"][relative]
    candidate["product_files"].update(delta["product_overrides"])
    candidate["product_files"].update(delta["product_files_additional"])
    candidate["protected_files"]["server.py"] = appeals_api["protected_files"]["server.py"]
    for relative in APPEALS_API_GUARD_OVERRIDES:
        candidate["guarded_files"][relative] = appeals_api["guarded_files"][relative]
    candidate["guarded_files"].update(delta["guarded_overrides"])
    candidate["guarded_files"].update(delta["guarded_additions"])
    return candidate


def load_stabilization_v2_contract(previous):
    raw = STABILIZATION_V2_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != STABILIZATION_V2_CONTRACT_SHA256:
        raise AssertionError("Changed exact Appeals scenario-readonly v2 manifest")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "product_files_additional", "protected_overrides", "guarded_overrides",
                       "guarded_additions"} or
            delta.get("variant_id") != STABILIZATION_V2_VARIANT_ID or
            delta.get("baseline_sha") != SCROLL_BASELINE or
            delta.get("base_manifest") != STABILIZATION_CONTRACT.name or
            delta.get("base_manifest_sha256") != STABILIZATION_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != STABILIZATION_V2_SCOPE or
            set(delta.get("product_overrides", {})) != STABILIZATION_V2_PRODUCT_OVERRIDES or
            set(delta.get("product_files_additional", {})) != STABILIZATION_V2_PRODUCT_ADDITIONS or
            set(delta.get("protected_overrides", {})) != {"server.py", "app.js"} or
            set(delta.get("guarded_overrides", {})) != STABILIZATION_V2_PRODUCT_OVERRIDES - {"server.py", "app.js"} or
            set(delta.get("guarded_additions", {})) != STABILIZATION_V2_PRODUCT_ADDITIONS or
            previous.get("variant_id") != STABILIZATION_V1_VARIANT_ID):
        raise AssertionError("Appeals scenario-readonly v2 has an unexpected exact scope")
    candidate = copy.deepcopy(previous)
    candidate["variant_id"] = STABILIZATION_V2_VARIANT_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                         set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["product_files"].update(delta["product_files_additional"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].pop("app.js", None)
    candidate["guarded_files"].update(delta["guarded_overrides"])
    candidate["guarded_files"].update(delta["guarded_additions"])
    return candidate


def load_stabilization_v3_contract(previous):
    raw = STABILIZATION_V3_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != STABILIZATION_V3_CONTRACT_SHA256:
        raise AssertionError("Changed exact scenario_context_snapshot v3 manifest")
    delta = json.loads(raw.decode("utf-8"))
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "product_files_additional", "protected_overrides", "guarded_overrides",
                       "guarded_additions"} or
            delta.get("variant_id") != STABILIZATION_V3_VARIANT_ID or
            delta.get("baseline_sha") != SCROLL_BASELINE or
            delta.get("base_manifest") != STABILIZATION_V2_CONTRACT.name or
            delta.get("base_manifest_sha256") != STABILIZATION_V2_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != STABILIZATION_V3_SCOPE or
            set(delta.get("product_overrides", {})) != STABILIZATION_V3_PRODUCT_OVERRIDES or
            set(delta.get("product_files_additional", {})) != STABILIZATION_V3_PRODUCT_ADDITIONS or
            set(delta.get("protected_overrides", {})) != {"server.py"} or
            set(delta.get("guarded_overrides", {})) != STABILIZATION_V3_PRODUCT_OVERRIDES - {"server.py"} or
            set(delta.get("guarded_additions", {})) != STABILIZATION_V3_PRODUCT_ADDITIONS or
            previous.get("variant_id") != STABILIZATION_V2_VARIANT_ID):
        raise AssertionError("scenario_context_snapshot v3 has an unexpected exact scope")
    candidate = copy.deepcopy(previous)
    candidate["variant_id"] = STABILIZATION_V3_VARIANT_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                         set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["product_files"].update(delta["product_files_additional"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    candidate["guarded_files"].update(delta["guarded_additions"])
    return candidate


def load_stabilization_v4_contract(previous):
    raw = STABILIZATION_V4_CONTRACT.read_bytes().replace(b"\r\n", b"\n")
    if sha256(raw) != STABILIZATION_V4_CONTRACT_SHA256:
        raise AssertionError("Changed exact full-scenario display v4 manifest")
    delta = json.loads(raw.decode("utf-8"))
    expected_guarded = STABILIZATION_V4_PRODUCT_OVERRIDES & set(previous["guarded_files"])
    if (set(delta) != {"variant_id", "baseline_sha", "base_manifest", "base_manifest_sha256",
                       "hash_format", "approved_scope_additions", "product_overrides",
                       "product_files_additional", "protected_overrides", "guarded_overrides", "guarded_additions"} or
            delta.get("variant_id") != STABILIZATION_VARIANT_ID or
            delta.get("baseline_sha") != SCROLL_BASELINE or
            delta.get("base_manifest") != STABILIZATION_V3_CONTRACT.name or
            delta.get("base_manifest_sha256") != STABILIZATION_V3_CONTRACT_SHA256 or
            delta.get("hash_format") != ADMIN_HASH_FORMAT or
            set(delta.get("approved_scope_additions", [])) != STABILIZATION_V4_SCOPE or
            set(delta.get("product_overrides", {})) != STABILIZATION_V4_PRODUCT_OVERRIDES or
            set(delta.get("product_files_additional", {})) != STABILIZATION_V4_PRODUCT_ADDITIONS or
            set(delta.get("protected_overrides", {})) != {"app.js"} or
            set(delta.get("guarded_overrides", {})) != expected_guarded or
            set(delta.get("guarded_additions", {})) != STABILIZATION_V4_PRODUCT_ADDITIONS or
            previous.get("variant_id") != STABILIZATION_V3_VARIANT_ID):
        raise AssertionError("Full-scenario display v4 has an unexpected exact scope")
    candidate = copy.deepcopy(previous)
    candidate["variant_id"] = STABILIZATION_VARIANT_ID
    candidate["approved_scope"] = sorted(set(candidate["approved_scope"]) |
                                         set(delta["approved_scope_additions"]))
    candidate["product_files"].update(delta["product_overrides"])
    candidate["product_files"].update(delta["product_files_additional"])
    candidate["protected_files"].update(delta["protected_overrides"])
    candidate["guarded_files"].update(delta["guarded_overrides"])
    candidate["guarded_files"].update(delta["guarded_additions"])
    return candidate
