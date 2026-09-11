import os
import tempfile
import time
import unittest
from pathlib import Path

from declension import (OverrideStore, decline_name, infer_entity_type,
                        normalize_document_name, normalize_lookup)


HEADER = "entity_type;original;genitive;dative;accusative;comment\n"


class DeclensionTests(unittest.TestCase):
    def empty_store(self, folder):
        return OverrideStore(Path(folder) / "missing.csv")

    def test_apps_script_legal_entity_parity(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.empty_store(folder)
            original = "КОМУНАЛЬНЕ ПІДПРИЄМСТВО «ДОБРО»"
            self.assertEqual(decline_name(original, "legal_entity", "genitive", store).value,
                             "КОМУНАЛЬНОГО ПІДПРИЄМСТВА «ДОБРО»")
            self.assertEqual(decline_name(original, "legal_entity", "accusative", store).value, original)

    def test_male_person_apps_script_parity(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.empty_store(folder)
            original = "БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ"
            self.assertEqual(decline_name(original, "person", "genitive", store).value,
                             "БОНДАРА СЕРГІЯ ВОЛОДИМИРОВИЧА")
            self.assertEqual(decline_name(original, "person", "accusative", store).value,
                             "БОНДАРА СЕРГІЯ ВОЛОДИМИРОВИЧА")

    def test_required_bondar_example_is_corrected_by_shipped_override(self):
        result = decline_name("БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ", "person", "genitive")
        self.assertEqual(result.value, "БОНДАРЯ СЕРГІЯ ВОЛОДИМИРОВИЧА")
        self.assertEqual(result.source, "override")

    def test_female_person_apps_script_parity(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.empty_store(folder)
            original = "КОВАЛЬСЬКА МАРІЯ ІВАНІВНА"
            self.assertEqual(decline_name(original, "person", "genitive", store).value,
                             "КОВАЛЬСЬКОЇ МАРІЇ ІВАНІВНИ")
            self.assertEqual(decline_name(original, "person", "accusative", store).value,
                             "КОВАЛЬСЬКУ МАРІЮ ІВАНІВНУ")

    def test_fop_prefix_and_person_parts_match_script(self):
        with tempfile.TemporaryDirectory() as folder:
            result = decline_name("ФОП БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ", "fop", "genitive", self.empty_store(folder))
            self.assertEqual(result.value, "ФІЗИЧНОЇ ОСОБИ-ПІДПРИЄМЦЯ БОНДАРА СЕРГІЯ ВОЛОДИМИРОВИЧА")
            self.assertEqual(result.source, "automatic")

    def test_override_normalizes_quotes_spaces_and_preserves_output(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "overrides.csv"
            path.write_text(HEADER + 'legal_entity;ТОВАРИСТВО «ПРИКЛАД»;Форма Р;Форма Д;Форма З;ручна\n', encoding="utf-8-sig")
            result = decline_name('  ТОВАРИСТВО   "ПРИКЛАД" ', "legal_entity", "genitive", OverrideStore(path))
            self.assertEqual((result.value, result.source), ("Форма Р", "override"))

    def test_dative_is_override_only(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = decline_name("БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ", "person", "dative", self.empty_store(folder))
            self.assertEqual((missing.status, missing.source, missing.value), ("unresolved", "unresolved", ""))
            path = Path(folder) / "overrides.csv"
            path.write_text(HEADER + "person;БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ;;БОНДАРЮ СЕРГІЮ ВОЛОДИМИРОВИЧУ;;manual\n", encoding="utf-8-sig")
            resolved = decline_name("БОНДАР СЕРГІЙ ВОЛОДИМИРОВИЧ", "person", "dative", OverrideStore(path))
            self.assertEqual((resolved.status, resolved.source, resolved.value),
                             ("resolved", "override", "БОНДАРЮ СЕРГІЮ ВОЛОДИМИРОВИЧУ"))

    def test_override_store_reloads_after_file_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "overrides.csv"
            path.write_text(HEADER + "person;ТЕСТ ІМ'Я ПОБАТЬКОВІ;ПЕРША;;;one\n", encoding="utf-8-sig")
            store = OverrideStore(path)
            self.assertEqual(store.form("ТЕСТ ІМ'Я ПОБАТЬКОВІ", "person", "genitive"), "ПЕРША")
            path.write_text(HEADER + "person;ТЕСТ ІМ'Я ПОБАТЬКОВІ;ДРУГА;;;two plus size\n", encoding="utf-8-sig")
            stamp = time.time_ns() + 2_000_000
            os.utime(path, ns=(stamp, stamp))
            self.assertEqual(store.form("ТЕСТ ІМ'Я ПОБАТЬКОВІ", "person", "genitive"), "ДРУГА")

    def test_quotes_preserved_and_unresolved_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.empty_store(folder)
            value = decline_name("ПРИВАТНЕ ПІДПРИЄМСТВО «ЛІНІЯ»", "legal_entity", "genitive", store).value
            self.assertEqual(value, "ПРИВАТНОГО ПІДПРИЄМСТВА «ЛІНІЯ»")
            result = decline_name("НЕВІДОМА ФОРМА", "other", "genitive", store)
            self.assertEqual((result.status, result.source, result.value), ("unresolved", "unresolved", ""))

    def test_entity_inference_and_lookup_normalization(self):
        self.assertEqual(infer_entity_type("ФОП БОНДАР СЕРГІЙ", "1234567890"), "fop")
        self.assertEqual(infer_entity_type("ТОВАРИСТВО «ДОБРО»", "12345678"), "legal_entity")
        self.assertEqual(normalize_lookup(' «Назва»  '), normalize_lookup('"Назва"'))

    def test_document_name_normalizes_only_paired_ascii_quotes(self):
        original = 'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ "ОХТИРКА М\'ЯСОПРОДУКТ"'
        expected = 'ТОВАРИСТВО З ОБМЕЖЕНОЮ ВІДПОВІДАЛЬНІСТЮ «ОХТИРКА М\'ЯСОПРОДУКТ»'
        self.assertEqual(normalize_document_name(original), expected)
        self.assertEqual(normalize_document_name(expected), expected)
        self.assertIn("М'ЯСОПРОДУКТ", normalize_document_name(original))


if __name__ == "__main__":
    unittest.main()
