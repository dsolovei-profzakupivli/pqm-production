import unittest

import document_quotes


class DocumentQuoteTests(unittest.TestCase):
    def test_ascii_outer_quotes_become_guillemets_without_touching_apostrophes(self):
        self.assertEqual(document_quotes.normalize_output_quotes('ТОВ "Вектор"'), 'ТОВ «Вектор»')
        self.assertEqual(document_quotes.normalize_output_quotes("Постачальник О'Браєн"), "Постачальник О'Браєн")

    def test_nested_quotes_use_inner_ukrainian_marks(self):
        self.assertEqual(document_quotes.normalize_output_quotes('ТОВ "Компанія "Вектор""'),
                         'ТОВ «Компанія „Вектор“»')
        self.assertEqual(document_quotes.normalize_output_quotes('«Компанія „Вектор“»'),
                         '«Компанія „Вектор“»')

    def test_unmatched_ambiguous_and_escaped_quotes_are_preserved(self):
        for value in ('Незавершена "назва', 'A"B', 'escaped \\"quote\\"'):
            with self.subTest(value=value):
                self.assertEqual(document_quotes.normalize_output_quotes(value), value)

    def test_multiple_pairs_and_nested_metadata_are_normalized_recursively(self):
        self.assertEqual(document_quotes.normalize_output_quotes('"Перше" та "друге"'),
                         '«Перше» та «друге»')
        self.assertEqual(document_quotes.normalize_output_tree({'askod': ['Тема "протоколу"']}),
                         {'askod': ['Тема «протоколу»']})


if __name__ == '__main__':
    unittest.main()
