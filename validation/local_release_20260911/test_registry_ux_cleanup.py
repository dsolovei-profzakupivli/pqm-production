import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class RegistryUxCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = (ROOT / "app.js").read_text(encoding="utf-8")
        cls.html = (ROOT / "index.html").read_text(encoding="utf-8")

    def test_manager_edit_refreshes_only_one_row(self):
        self.assertIn("await refreshOneRow(row)", self.app)
        manager_branch = self.app.split("if(key==='managerName')", 1)[1].split("}catch", 1)[0]
        self.assertNotIn("loadRows()", manager_branch)

    def test_primary_category_and_officer_filters_are_visible(self):
        self.assertIn('id="applicationCategoryFilter"', self.html)
        self.assertIn('id="applicationOfficerFilter"', self.html)
        self.assertIn("categoryFilter=$('#applicationCategoryFilter').value", self.app)

    def test_decision_kpis_are_independent_of_protocol_requisites(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        for key, value in (("decision_yes", "admit"), ("decision_no", "reject")):
            self.assertIn(f"af.protocol_decision='{value}' THEN 1 ELSE 0 END) {key}", source)
        self.assertIn("COALESCE(af.protocol_decision,'')='' THEN 1 ELSE 0 END) decision_undefined", source)
        stats = source.split("def application_stats", 1)[1].split("def list_applications", 1)[0]
        self.assertNotIn("protocol_number", stats)
        self.assertNotIn("protocol_date", stats)

    def test_supplier_code_actions_have_fixed_right_columns(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".supplier-code-actions{display:grid;grid-template-columns:minmax(0,1fr) 25px", styles)
        self.assertIn("column-gap:9px", styles)

    def test_legacy_protocol_marker_is_compact(self):
        branch = self.app.split("if(col.key==='protocolNumber'&&row.legacyProtocol)", 1)[1].split("if(col.key==='number')", 1)[0]
        self.assertIn('title="Legacy: сформований раніше"', branch)
        self.assertNotIn('<small class="muted">Legacy:', branch)

    def test_toasts_use_browser_top_layer(self):
        self.assertIn('id="toast" class="toast-stack" role="status" aria-live="polite" popover="manual"', self.html)
        self.assertIn("stack.showPopover", self.app)

    def test_remark_add_and_edit_share_modal_not_prompt(self):
        self.assertIn('id="referenceRemarkDialog"', self.html)
        editor = self.app.split("function openReferenceRemarkEditor", 1)[1].split("async function removeReferenceRemark", 1)[0]
        self.assertIn("showModal()", editor)
        self.assertNotIn("prompt(", editor)

    def test_compact_toolbar_includes_marketplace_action_filter(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn('class="toolbar card applications-toolbar"', self.html)
        ordered = ["searchInput", "applicationCategoryFilter", "statusFilter",
                   "marketplaceDecisionFilter", "profileSelect", "saveProfileBtn",
                   "clearFiltersBtn"]
        positions = [self.html.index(f'id="{item}"') for item in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("marketplace_decision", self.app)
        self.assertIn('multi_param(params, "marketplace_decision")', source)

    def test_bulk_fill_uses_apply_field_value_rows_and_disables_unchecked_controls(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        bulk = self.app.split("function openBulk(){", 1)[1].split("async function applyBulk", 1)[0]
        self.assertIn("Застосувати</span><span>Поле</span><span>Значення", bulk)
        self.assertIn("control.disabled=!item.checked", bulk)
        self.assertLess(bulk.index("managerName:'"), bulk.index("protocolRemarks:'"))
        self.assertIn("#bulkDialog form{display:flex", styles)
        self.assertIn("resize:vertical", styles)

    def test_framework_title_is_optional_column_and_search_hint(self):
        self.assertIn("key:'frameworkTitle'", self.app)
        self.assertIn("visible:false", self.app)
        self.assertIn("керівник, відбір, код ДК, договір", self.html)

    def test_pinned_columns_share_key_width_and_offset_model(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('data-column-key="${col.key}"', self.app)
        self.assertIn('data-column-key="${c.key}"', self.app)
        self.assertIn("const attrs=(extra='')", self.app)
        self.assertIn("attrs('participant-note-cell')", self.app)
        self.assertNotIn('class="${sticky}', self.app)
        self.assertIn("max-width:${col.width}px", self.app)
        self.assertIn("max-width:${c.width}px", self.app)
        self.assertIn("table.style.width=`${tableWidth}px`", self.app)
        self.assertNotIn("c.pin=base.pin||''", self.app)
        self.assertIn("#applicationsTable{table-layout:fixed}", styles)

    def test_marketplace_filter_never_displays_technical_values(self):
        self.assertIn("marketplaceFilterLabels={__empty__:'Не виконано',admit:'Допустити',reject:'Відхилити'}", self.app)
        binding = "bindStaticMulti('marketplaceDecisionFilter',filterSelections.marketplace,'Дія на майданчику',value=>marketplaceFilterLabels[value]||value)"
        self.assertIn(binding, self.app)

    def test_profile_persists_columns_pins_widths_and_kpis(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertIn("function persistProfileLayout()", self.app)
        self.assertIn("JSON.stringify({columns:p.columns,kpis:p.kpis,sorts:p.sorts||multiSort})", self.app)
        self.assertIn("p.kpis=[...(source.kpis||defaultKpis(source.name))]", self.app)
        self.assertIn('"pin": "left" if raw.get("pin") == "left" else ""', source)
        self.assertIn('"kpis": _validated_profile_kpis(kpis)', source)

    def test_remarks_dialog_is_wider_without_fullscreen(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".remarks-dialog{width:min(980px,calc(100vw - 30px))}", styles)

    def test_document_results_use_compact_category_badges(self):
        self.assertIn("doc-category-badge", self.app)
        self.assertIn("documentCheckCategories", self.app)
        self.assertNotIn('id="saveDocumentReviewBtn"', self.html)

    def test_document_experience_uses_contract_links_not_document_ocr_tag(self):
        self.assertNotIn("['experience','Досвід']", self.app)
        self.assertIn("item.key==='contract_experience'", self.app)
        self.assertIn("row.url", self.app)
        self.assertIn("contract-experience-marker", self.app)
        self.assertIn("found?'+'\u003a'−'", self.app)
        self.assertIn("const labels={signature:'КЕП',mvs:'МВС'}", self.app)
        self.assertNotIn("КЕП',mvs:'МВС',experience:'Договори", self.app)
        self.assertIn(" · не перевірено", self.app)

    def test_first_page_render_does_not_wait_for_statistics(self):
        loader = self.app.split("async function loadRows(){", 1)[1].split("function bindStaticMulti", 1)[0]
        self.assertIn("const data=await request(`${API}/applications?${q}`)", loader)
        self.assertNotIn("Promise.all", loader)
        self.assertIn("render();if(refreshStats)void loadStats()", loader)

    def test_reload_does_not_restore_last_supplier_modal(self):
        self.assertNotIn("supplierProfile=", self.app)
        self.assertNotIn("openSupplierProfile(new URLSearchParams", self.app)
        self.assertIn("if(button)openSupplierProfile(button.dataset.supplierCode)", self.app)

    def test_framework_search_ignores_stale_responses(self):
        self.assertIn("frameworkRequestSequence", self.app)
        self.assertIn("if(requestSequence!==frameworkRequestSequence)return", self.app)

    def test_framework_search_enriches_bids_candidates_with_local_titles(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        analytics = source.split("def framework_analytics(params: dict)", 1)[1].split(
            "def framework_analytics_details", 1)[0]
        self.assertIn("title_match_agreement_ids", analytics)
        self.assertIn('("id", "pretty_id", "title", "dk_code", "agreement_id")', analytics)

    def test_work_queue_reason_uses_separate_lines(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn("return result.split(' · ').join('\\n')", self.app)
        self.assertIn("#workQueueBody td:nth-child(2) small{white-space:pre-line}", styles)

    def test_supplier_auxiliary_failures_have_controlled_messages(self):
        self.assertIn("Не вдалося отримати стан синхронізації ЄДР", self.app)
        self.assertIn("Не вдалося отримати стан синхронізації перевірок НАЗК", self.app)

    def test_supplier_manager_source_is_a_secondary_line_below_name(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('class="supplier-manager-source"', self.app)
        self.assertIn(".supplier-manager-source{display:block", styles)
        self.assertIn("font-size:10px", styles.split(".supplier-manager-source", 1)[1].split("}", 1)[0])

    def test_supplier_note_dialog_has_full_width_body_and_explicit_clear(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('id="supplierNoteClear"', self.html)
        self.assertIn('class="supplier-note-body"', self.html)
        self.assertIn("$('#supplierNoteClear').hidden=viewer||!row.supplierNote", self.app)
        self.assertIn("saveSupplierNote('','Спільну примітку очищено')", self.app)
        self.assertIn("min-height:110px", styles)
        self.assertIn("resize:vertical", styles)

    def test_history_replaces_cancelled_failed_block(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        self.assertNotIn('Попередні невдалі заявки ·', self.app)
        self.assertIn('supplierAllApplications', self.app)
        self.assertIn('COALESCE(af.protocol_officer,\'\') protocol_officer', source)
        self.assertIn('SELECT q2.id FROM qualifications q2 WHERE q2.submission_id=s.id', source)

    def test_violation_completion_is_one_atomic_request(self):
        completion = self.app.split("async function completeViolationReview(item)", 1)[1].split(
            "const bindViolationProtocolBase", 1)[0]
        self.assertIn("const payload=collectViolationReview()", completion)
        self.assertIn("body:JSON.stringify(payload)", completion)
        self.assertNotIn("method:'PATCH'", completion)

    def test_local_completion_renders_review_and_snapshot_separately_from_prozorro(self):
        self.assertIn("item.read_only_reason==='local_completion'", self.app)
        self.assertIn("Офіційне рішення Prozorro ще не оприлюднено", self.app)
        self.assertIn("Збережений контекст рішення", self.app)
        self.assertIn("c.dk_code", self.app)
        self.assertIn("rec.recommendation_reason", self.app)
        self.assertIn("r.decision_justification", self.app)

    def test_read_only_review_details_are_closed_accordion_below_decision(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<details class="violation-review-accordion">', self.app)
        self.assertNotIn('<details class="violation-review-accordion" open', self.app)
        self.assertIn('<summary>Деталі розгляду УО</summary>', self.app)
        self.assertIn("official+accordion", self.app)
        helper = self.app.split("function violationReadOnlyReviewHtml(item)", 1)[1].split(
            "function violationReviewAccordion", 1)[0]
        self.assertIn("ПЕРЕВІРКА УО", helper)
        self.assertNotIn("Рішення Адміністратора", helper)
        self.assertIn(".violation-review-accordion", styles)

    def test_registry_active_filters_and_single_page_scroll_are_preserved(self):
        styles = (ROOT / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".filter-active", styles)
        self.assertIn("toggle('#dateFromFilter',$('#dateFromFilter').value)", self.app)
        self.assertIn("toggle('#dateToFilter',$('#dateToFilter').value)", self.app)
        self.assertIn("toggle('#protocolDecisionFilter',$('#protocolDecisionFilter').value)", self.app)
        self.assertIn("toggle('#complianceStatusFilter',$('#complianceStatusFilter').value)", self.app)
        self.assertIn("toggle('#registryStatusFilter',filterSelections.registry.size)", self.app)
        self.assertIn("toggle('#supplierCodeFilter',filterSelections.supplier.size)", self.app)
        self.assertIn("toggle('#frameworkFilter',filterSelections.framework.size)", self.app)
        self.assertIn("toggle('#dkFilter',filterSelections.dk.size)", self.app)
        self.assertIn("$('#dateFromFilter').value,$('#dateToFilter').value", self.app)
        self.assertIn("overflow-y:visible", styles)
        self.assertIn("overflow-x:auto", styles)

    def test_nested_framework_and_dk_popovers_keep_advanced_filter_open(self):
        advanced_start = self.html.index('<details class="advanced-filters">')
        advanced_end = self.html.index('id="profileSelect"', advanced_start)
        self.assertLess(
            advanced_start,
            self.html.index('id="frameworkFilter" class="multi-filter', advanced_start, advanced_end),
        )
        self.assertLess(
            advanced_start,
            self.html.index('id="dkFilter" class="multi-filter', advanced_start, advanced_end),
        )
        coordinator = self.app.split("document.addEventListener('toggle'", 1)[1].split(
            "document.addEventListener('pointerdown'", 1)[0]
        self.assertIn("!item.contains(opened)", coordinator)
        self.assertNotIn(
            "item!==opened&&item instanceof HTMLDetailsElement)item.open=false",
            coordinator,
        )

    def test_application_nazk_marker_uses_submission_presentation_only(self):
        row_renderer = self.app.split("function render(){", 1)[1].split(
            "function bindStaticMulti", 1
        )[0]
        self.assertIn("row.nazkPresentationState==='needs_check'", self.app)
        self.assertIn("applicationNazk=r.nazkPresentationState", row_renderer)
        self.assertNotIn("pending&&r.nazkReviewResult", row_renderer)
        self.assertNotIn("pending&&r.nazkMatch", row_renderer)

    def test_registry_reset_clears_hidden_submission_deep_link(self):
        self.assertIn("function clearApplicationDeepLinkFilter()", self.app)
        helper = self.app.split("function clearApplicationDeepLinkFilter()", 1)[1].split(
            "function syncPrimaryFilters", 1
        )[0]
        self.assertIn("deepLinkSubmissionId=''", helper)
        self.assertIn("url.searchParams.delete('submission_id')", helper)
        self.assertIn("url.searchParams.delete('nazk_control')", helper)
        reset = self.app.split("$('#clearFiltersBtn').onclick=", 1)[1].split("$('#columnsBtn')", 1)[0]
        self.assertIn("clearApplicationDeepLinkFilter()", reset)
        self.assertIn("event.target.closest('#applicationsNav')", self.app)

    def test_officer_names_share_one_presentation_formatter(self):
        history = (ROOT / "history_columns.js").read_text(encoding="utf-8")
        self.assertIn(
            "displayValue=['protocolOfficer','reviewOfficer'].includes(col.key)?formatOfficerName",
            self.app,
        )
        self.assertIn("esc(formatOfficerName(value))", self.app)
        self.assertIn("officer:esc(formatOfficerName(x.protocol_officer)||'—')", history)


if __name__ == "__main__":
    unittest.main()
