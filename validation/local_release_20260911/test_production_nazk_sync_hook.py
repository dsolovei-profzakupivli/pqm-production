"""Guard successful synchronization hooks without importing the application."""
import ast
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE if (HERE / "server.py").exists() else Path(__file__).resolve().parents[2]


def function_nodes(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}


def calls(node, name):
    return [child for child in ast.walk(node) if isinstance(child, ast.Call) and
            ((isinstance(child.func, ast.Name) and child.func.id == name) or
             (isinstance(child.func, ast.Attribute) and child.func.attr == name))]


class ProductionNazkSyncHookTests(unittest.TestCase):
    def test_all_prozorro_sync_modes_run_guarded_nazk_reconciliation(self):
        functions = function_nodes(ROOT / "server.py")
        self.assertEqual(len(calls(functions["reconcile_nazk_tasks_after_complete_prozorro_sync"],
                                  "reconcile_stale_nazk_tasks_after_prozorro_sync")), 1)
        for name in ("sync_worker", "sync_all_worker", "sync_incremental_worker"):
            with self.subTest(worker=name):
                node = functions[name]
                self.assertEqual(len(calls(node, "reconcile_nazk_tasks_after_complete_prozorro_sync")), 1)
                self.assertEqual(len(calls(node, "sync_all_tracked_frameworks")) if name == "sync_all_worker" else 0,
                                 1 if name == "sync_all_worker" else 0)

    def test_post_sync_guard_requires_complete_nonempty_result(self):
        source = (ROOT / "operational_tasks.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and
                    n.name == "reconcile_stale_nazk_tasks_after_prozorro_sync")
        text = ast.unparse(node)
        for contract in ("frameworks <= 0", "completed != frameworks", "sync_not_complete",
                         "errors", "officer_assignments_error", "reconcile_stale_nazk_tasks"):
            with self.subTest(contract=contract):
                self.assertIn(contract, text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
