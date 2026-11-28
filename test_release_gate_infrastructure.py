"""Regression tests for local Release Gate staging and isolation adapters."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import textwrap
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import zipfile

import validation.run_local_release as release
import validation.docker_release_gate as docker_gate
import validation.run_c246_historical_integrity_snapshots_v1 as c246_snapshots
import validation.document_release_history_v2 as document_history


ROOT = Path(__file__).resolve().parent


def repository_root(test_file=__file__):
    """Use the original checkout when tests are copied into a disposable tree."""
    configured = os.environ.get("PQM_RELEASE_SOURCE_ROOT")
    return Path(configured).resolve() if configured else Path(test_file).resolve().parent


REPOSITORY_ROOT = repository_root()
V31_GITHUB_ROUTE = "validation/v31_1/bridge.py --entrypoint github --phase python"
V31_GITHUB_RUN_COMMANDS_SHA256 = "8db52fef836166b8ee51f7f53765fffe139b8209178b39f82f864408e8cfda89"


def _workflow_steps(workflow):
    """Read step structure without binding the contract to YAML indentation width."""
    lines = workflow.splitlines()
    start_matches = [(index, len(match.group(1)), match.group(2))
                     for index, line in enumerate(lines)
                     if (match := re.match(r"^( *)-\s+name:\s*(.*?)\s*$", line))]
    if not start_matches:
        return []
    step_indent = min(indent for _, indent, _ in start_matches)
    starts = [(index, name) for index, indent, name in start_matches if indent == step_indent]
    steps = []
    for position, (start, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        block = lines[start:end]
        step = {"name": name, "run": None,
                "shell": None, "if": None, "continue-on-error": False}
        field_lines = []
        for line in block[1:]:
            match = re.match(r"^( *)((?:run|shell|if|continue-on-error)):\s*(.*?)\s*$", line)
            if match and len(match.group(1)) > step_indent:
                field_lines.append((len(match.group(1)), match.group(2), match.group(3)))
        if not field_lines:
            steps.append(step)
            continue
        field_indent = min(indent for indent, _, _ in field_lines)
        index = 1
        while index < len(block):
            match = re.match(r"^( *)((?:run|shell|if|continue-on-error)):\s*(.*?)\s*$", block[index])
            if not match or len(match.group(1)) != field_indent:
                index += 1
                continue
            key, value = match.group(2), match.group(3).strip()
            if key == "run" and value in {"|", "|-", "|+"}:
                content = []
                index += 1
                while index < len(block):
                    child = block[index]
                    child_indent = len(child) - len(child.lstrip(" "))
                    if child.strip() and child_indent <= field_indent:
                        break
                    content.append(child)
                    index += 1
                content_indent = min(
                    len(line) - len(line.lstrip(" ")) for line in content if line.strip()
                ) if any(line.strip() for line in content) else field_indent + 1
                step["run"] = "\n".join(
                    line[content_indent:] if line.strip() else "" for line in content
                )
                continue
            if key == "shell":
                step["shell"] = _yaml_scalar_without_comment(value).strip("'\"")
            elif key == "if":
                step["if"] = _yaml_scalar_without_comment(value).strip("'\"") or None
            elif key == "continue-on-error":
                step["continue-on-error"] = (
                    _yaml_scalar_without_comment(value).lower().strip("'\"") == "true"
                )
            index += 1
        steps.append(step)
    return steps


def _shell_commands(script):
    """Tokenize simple shell statements, honoring comments, quotes, and continuations."""
    result = []
    pending = ""
    for physical in script.splitlines():
        line = physical.strip()
        if not line:
            continue
        continued = line.endswith("\\")
        pending += (line[:-1] if continued else line) + " "
        if continued:
            continue
        lexer = shlex.shlex(pending, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
        if tokens:
            result.append(tokens)
        pending = ""
    if pending:
        lexer = shlex.shlex(pending, posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
        if tokens:
            result.append(tokens)
    return result


def _yaml_scalar_without_comment(value):
    """Remove a YAML trailing comment while preserving quoted # characters."""
    quote = None
    escaped = False
    index = 0
    while index < len(value):
        char = value[index]
        if quote == "'":
            if char == "'":
                if index + 1 < len(value) and value[index + 1] == "'":
                    index += 1
                else:
                    quote = None
        elif quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            quote = char
        elif char == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
        index += 1
    return value.strip()


def _shell_comment_start(command):
    """Return the first active shell-comment offset, respecting escapes and quotes."""
    quote = None
    escaped = False
    for index, char in enumerate(command):
        if quote == "'":
            if char == "'":
                quote = None
        elif quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = None
        elif escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char in {"'", '"'}:
            quote = char
        elif char == "#" and (index == 0 or command[index - 1].isspace()):
            return index
    return None


def _insert_before_shell_comment(command, addition):
    """Add active shell syntax before a trailing comment, never inside it."""
    comment_start = _shell_comment_start(command)
    if comment_start is None:
        return command.rstrip() + " " + addition
    active = command[:comment_start].rstrip()
    comment = command[comment_start:]
    return active + " " + addition + " " + comment


def _validated_v31_workflow_step(workflow):
    candidates = [step for step in _workflow_steps(workflow)
                  if isinstance(step["run"], str) and "validation/v31_1/bridge.py" in step["run"]
                  and "--phase python" in step["run"]]
    if len(candidates) != 1:
        raise AssertionError(f"Expected one V31.1 bridge workflow step; found {len(candidates)}")
    step = candidates[0]
    if step["if"] is not None:
        raise AssertionError("V31.1 workflow step must be unconditional")
    if step["continue-on-error"]:
        raise AssertionError("V31.1 workflow step is allowed to fail")
    if step["shell"] != "bash":
        raise AssertionError(f"V31.1 workflow step must use bash, got {step['shell']!r}")
    commands = _shell_commands(step["run"])
    command_fingerprint = hashlib.sha256(
        json.dumps(commands, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if command_fingerprint != V31_GITHUB_RUN_COMMANDS_SHA256:
        raise AssertionError("V31.1 workflow command sequence changed from its approved fail-closed contract")
    if not commands or commands[0] != ["set", "-euo", "pipefail"]:
        raise AssertionError("V31.1 workflow must begin with the approved fail-fast shell mode")
    route_commands = [tokens for tokens in commands
                      if any("validation/v31_1/bridge.py" in token for token in tokens)]
    if len(route_commands) != 1:
        raise AssertionError(f"Expected one executable V31.1 bridge invocation; found {len(route_commands)}")
    expected = ["$RUNNER_TEMP/pqm-release-python/bin/python", "-B",
                "validation/v31_1/bridge.py", "--entrypoint", "github", "--phase", "python",
                "--evidence", "$RUNNER_TEMP/pqm-v311-evidence"]
    if route_commands[0] != expected:
        raise AssertionError(f"V31.1 bridge is not a direct required invocation: {route_commands[0]!r}")
    return step


class ReleaseGateInfrastructureTests(unittest.TestCase):
    def test_v311_route_is_active_and_negative_mutations_fail_closed(self):
        workflow_path = REPOSITORY_ROOT / ".github/workflows/release-checks.yml"
        workflow = workflow_path.read_text(encoding="utf-8")
        step = _validated_v31_workflow_step(workflow)
        self.assertIn(V31_GITHUB_ROUTE, step["run"])

        runner = (REPOSITORY_ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        runner_ast = ast.parse(runner)
        main = next(node for node in runner_ast.body
                    if isinstance(node, ast.FunctionDef) and node.name == "main")
        route_calls = [node for node in ast.walk(main)
                       if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                       and isinstance(node.func.value, ast.Name) and node.func.value.id == "v311"
                       and node.func.attr == "route_suite"]
        self.assertEqual(len(route_calls), 1, "The stock local entrypoint must route its suite through V31.1")
        route_call = route_calls[0]
        self.assertEqual([keyword.arg for keyword in route_call.keywords], ["required"])
        self.assertIsInstance(route_call.keywords[0].value, ast.Name)
        self.assertEqual(route_call.keywords[0].value.id, "full_candidate_run")

        def change_route_line(transform, text=workflow):
            lines = text.splitlines(keepends=True)
            hits = [index for index, line in enumerate(lines) if V31_GITHUB_ROUTE in line]
            self.assertEqual(len(hits), 1)
            index = hits[0]
            body = lines[index].rstrip("\r\n")
            newline = lines[index][len(body):]
            indent = body[:len(body) - len(body.lstrip())]
            lines[index] = transform(indent, body[len(indent):]) + newline
            return "".join(lines)

        def mutate_route_step_field(text, field, replacement):
            header = "      - name: " + step["name"] + "\n"
            start = text.index(header)
            next_step = re.search(r"(?m)^      - name: ", text[start + len(header):])
            end = start + len(header) + next_step.start() if next_step else len(text)
            block = text[start:end]
            pattern = rf"(?m)^([ ]*{re.escape(field)}:\s*[^\r\n]*?)\s*$"
            changed, count = re.subn(pattern, replacement, block, count=1)
            self.assertEqual(count, 1, f"Expected one {field} field in required workflow step")
            return text[:start] + changed + text[end:]

        route_step_header = "      - name: " + step["name"] + "\n"
        command_contract_error = (
            "V31.1 workflow command sequence changed from its approved fail-closed contract"
        )
        mutations = {
            "commented command": (
                change_route_line(lambda indent, body: indent + "# " + body),
                command_contract_error,
            ),
            "deleted command": (
                change_route_line(lambda indent, body: indent + "true"),
                "Expected one V31.1 bridge workflow step; found 0",
            ),
            "wrong version route": (
                change_route_line(
                    lambda indent, body: indent + body.replace("--phase python", "--phase unit", 1)),
                "Expected one V31.1 bridge workflow step; found 0",
            ),
            "disabled required step": (
                workflow.replace(route_step_header, route_step_header + "        if: false\n", 1),
                "V31.1 workflow step must be unconditional",
            ),
            "echo instead of execution": (
                change_route_line(lambda indent, body: indent + "echo " + body),
                command_contract_error,
            ),
            "swallowed failure": (
                change_route_line(
                    lambda indent, body: indent + _insert_before_shell_comment(body, "|| true")
                ),
                command_contract_error,
            ),
            "continue on error": (
                workflow.replace(
                    route_step_header, route_step_header + "        continue-on-error: true\n", 1),
                "V31.1 workflow step is allowed to fail",
            ),
        }
        def insert_before_route(text, inserted):
            lines = text.splitlines(keepends=True)
            hits = [index for index, line in enumerate(lines) if V31_GITHUB_ROUTE in line]
            self.assertEqual(len(hits), 1)
            index = hits[0]
            indent = lines[index][:len(lines[index]) - len(lines[index].lstrip())]
            lines.insert(index, indent + inserted + "\n")
            return "".join(lines)

        def append_after_route(text, inserted):
            lines = text.splitlines(keepends=True)
            hits = [index for index, line in enumerate(lines) if V31_GITHUB_ROUTE in line]
            self.assertEqual(len(hits), 1)
            index = hits[0]
            indent = lines[index][:len(lines[index]) - len(lines[index].lstrip())]
            lines.insert(index + 1, indent + inserted + "\n")
            return "".join(lines)

        harmless_shell_comment = change_route_line(
            lambda indent, body: indent + body + " # harmless trailing comment"
        )
        harmless_yaml_comment = mutate_route_step_field(
            workflow, "shell", r"\1 # harmless YAML comment"
        )
        positive_variants = {
            "unchanged workflow": workflow,
            "extra blank line": append_after_route(workflow, ""),
            "standalone shell comment": insert_before_route(workflow, "# harmless comment"),
            "YAML comment after shell value": harmless_yaml_comment,
            "shell comment after bridge": harmless_shell_comment,
            "both harmless comments": mutate_route_step_field(
                harmless_shell_comment, "shell", r"\1 # harmless YAML comment"
            ),
        }
        for label, candidate in positive_variants.items():
            with self.subTest(positive_variant=label):
                self.assertEqual(_validated_v31_workflow_step(candidate)["shell"], "bash")

        for quoted_hash, expected_value in (
            ('runner --value "quoted # value" # trailing comment', "quoted # value"),
            ("runner --value 'quoted # value' # trailing comment", "quoted # value"),
            (r"runner --value escaped\#value # trailing comment", "escaped#value"),
        ):
            with self.subTest(quoted_hash=quoted_hash):
                commented_mutation = _insert_before_shell_comment(quoted_hash, "|| true")
                self.assertEqual(
                    _shell_commands(commented_mutation),
                    [["runner", "--value", expected_value, "||", "true"]],
                )

        mutations["disable errexit before bridge"] = (
            insert_before_route(workflow, "set +e"), command_contract_error
        )
        mutations["disable errexit then continue successfully"] = (
            append_after_route(insert_before_route(workflow, "set +e"), "true"),
            command_contract_error,
        )
        mutations["swallowed failure before trailing shell comment"] = (
            change_route_line(
                lambda indent, body: indent + _insert_before_shell_comment(body, "|| true"),
                text=harmless_shell_comment,
            ),
            command_contract_error,
        )
        for label, (mutated, expected_error) in mutations.items():
            with self.subTest(mutation=label), self.assertRaisesRegex(
                AssertionError, re.escape(expected_error)
            ):
                _validated_v31_workflow_step(mutated)

        child_script = textwrap.dedent("""
            import sys, unittest
            import validation.v31_1.bridge as bridge
            class CandidateEdRTest(unittest.TestCase):
                def runTest(self): pass
            CandidateEdRTest.__module__ = 'test_edr_sync_v2'
            routed = bridge.route_suite(unittest.TestSuite([CandidateEdRTest()]), '.', 'local', required=True)
            def fail_required_delegate(*args, **kwargs): raise RuntimeError('synthetic required delegate failure')
            bridge.phase = fail_required_delegate
            result = unittest.TextTestRunner(verbosity=2).run(routed)
            raise SystemExit(0 if result.wasSuccessful() else 23)
        """)
        delegate = subprocess.run([sys.executable, "-B", "-c", child_script],
                                  cwd=REPOSITORY_ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(delegate.returncode, 23, delegate.stdout + delegate.stderr)
        self.assertIn("ERROR", delegate.stderr)
        self.assertIn("synthetic required delegate failure", delegate.stderr)

    def test_document_baseline_hydrates_v31_changed_styles_from_pinned_addendum(self):
        accepted = document_history.baseline_root(REPOSITORY_ROOT)
        raw = (accepted / "styles.css").read_bytes()
        self.assertEqual(
            document_history.blob_oid(raw),
            "163cc4473c4e07c8aa1647275580da6008a5b242",
        )
        self.assertNotEqual(raw, (REPOSITORY_ROOT / "styles.css").read_bytes())
        accepted_test = (accepted / "validation/local_release_20260911/test_edr_sync_v2.py").read_bytes()
        self.assertEqual(
            document_history.blob_oid(accepted_test),
            "bae88092eeb56300186c1248d19b3d9885c2e2f8",
        )
        self.assertNotEqual(
            accepted_test,
            (REPOSITORY_ROOT / "validation/local_release_20260911/test_edr_sync_v2.py").read_bytes(),
        )

    def test_uncaught_worker_exception_is_reported_as_gate_failure(self):
        script = textwrap.dedent("""
            import threading
            from validation.run_local_release import UnhandledThreadExceptionMonitor

            previous = threading.excepthook
            monitor = UnhandledThreadExceptionMonitor()
            monitor.install()
            try:
                def fail_worker():
                    raise RuntimeError('synthetic background failure')

                worker = threading.Thread(target=fail_worker, name='release-test-worker')
                worker.start()
                worker.join(timeout=2)
                assert not worker.is_alive()
                assert not monitor.report()
                assert monitor.exceptions
            finally:
                monitor.restore()
            assert threading.excepthook is previous
        """)
        result = release.run_release_subprocess(
            [sys.executable, '-B', '-c', script], cwd=REPOSITORY_ROOT,
            capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('RELEASE GATE FAIL: uncaught exception in background thread release-test-worker',
                      result.stderr)

    def test_release_child_environment_drops_only_git_config_overrides(self):
        original = {
            "PATH": "kept-path",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "safe.directory",
            "GIT_CONFIG_VALUE_0": "*",
            "GIT_CONFIG_PARAMETERS": "--global",
            "CUSTOM_SETTING": "kept-value",
        }
        child = release.release_subprocess_environment(original)
        self.assertEqual(child["PATH"], "kept-path")
        self.assertEqual(child["CUSTOM_SETTING"], "kept-value")
        self.assertFalse(any(key.startswith("GIT_CONFIG_") for key in child))
        self.assertEqual(original["GIT_CONFIG_VALUE_0"], "*")

    def test_docker_gate_forwards_only_integrated_snapshot_archive_inputs(self):
        source = {
            "PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE": "/tmp/v10.zip",
            "PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE_SHA256": "a" * 64,
            "PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE": "/tmp/v24.zip",
            "PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_SHA256": "b" * 64,
            "PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_OUT": "/tmp/should-not-forward.zip",
            "PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE": "/tmp/v25.zip",
            "PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_SHA256": "c" * 64,
            "PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_OUT": "/tmp/should-not-forward-v25.zip",
            "PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE": "/tmp/v26.zip",
            "PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE_SHA256": "d" * 64,
            "PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE_OUT": "/tmp/should-not-forward-v26.zip",
            "PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE": "/tmp/v27.zip",
            "PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE_SHA256": "e" * 64,
            "PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE_OUT": "/tmp/should-not-forward-v27.zip",
            "PQM_INTEGRATED_V28_SNAPSHOT_ARCHIVE": "/tmp/v28-sandbox.zip",
            "PQM_INTEGRATED_V28_SNAPSHOT_ARCHIVE_SHA256": "1" * 64,
            "PQM_INTEGRATED_V127_SNAPSHOT_ARCHIVE": "/tmp/v27-candidate.zip",
            "PQM_INTEGRATED_V127_SNAPSHOT_ARCHIVE_SHA256": "2" * 64,
            "PQM_INTEGRATED_V128_SNAPSHOT_ARCHIVE": "/tmp/v28-candidate.zip",
            "PQM_INTEGRATED_V128_SNAPSHOT_ARCHIVE_SHA256": "3" * 64,
            "PQM_INTEGRATED_V29_SNAPSHOT_ARCHIVE": "/tmp/v29-candidate.zip",
            "PQM_INTEGRATED_V29_SNAPSHOT_ARCHIVE_SHA256": "4" * 64,
            "PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE": "/tmp/v30-candidate.zip",
            "PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE_SHA256": "6" * 64,
            "PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE": "/tmp/update-append-v26.zip",
            "PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE_SHA256": "5" * 64,
            "GOOGLE_WRITER_TOKEN": "must-not-forward",
            "PATH": "untrusted-path",
        }
        env = docker_gate.isolated_test_environment(source)

        self.assertEqual(env["PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE"], "/tmp/v10.zip")
        self.assertEqual(env["PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE_SHA256"], "a" * 64)
        self.assertEqual(env["PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE"], "/tmp/v24.zip")
        self.assertEqual(env["PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_SHA256"], "b" * 64)
        self.assertNotIn("PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_OUT", env)
        self.assertEqual(env["PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE"], "/tmp/v25.zip")
        self.assertEqual(env["PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_SHA256"], "c" * 64)
        self.assertNotIn("PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_OUT", env)
        self.assertEqual(env["PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE"], "/tmp/v26.zip")
        self.assertEqual(env["PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE_SHA256"], "d" * 64)
        self.assertNotIn("PQM_INTEGRATED_V26_SNAPSHOT_ARCHIVE_OUT", env)
        self.assertEqual(env["PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE"], "/tmp/v27.zip")
        self.assertEqual(env["PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE_SHA256"], "e" * 64)
        self.assertNotIn("PQM_INTEGRATED_V27_SNAPSHOT_ARCHIVE_OUT", env)
        self.assertEqual(env["PQM_INTEGRATED_V28_SNAPSHOT_ARCHIVE"], "/tmp/v28-sandbox.zip")
        self.assertEqual(env["PQM_INTEGRATED_V127_SNAPSHOT_ARCHIVE"], "/tmp/v27-candidate.zip")
        self.assertEqual(env["PQM_INTEGRATED_V128_SNAPSHOT_ARCHIVE"], "/tmp/v28-candidate.zip")
        self.assertEqual(env["PQM_INTEGRATED_V29_SNAPSHOT_ARCHIVE"], "/tmp/v29-candidate.zip")
        self.assertEqual(env["PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE"], "/tmp/v30-candidate.zip")
        self.assertEqual(env["PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE_SHA256"], "6" * 64)
        self.assertEqual(env["PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE"], "/tmp/update-append-v26.zip")
        self.assertEqual(env["PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE_SHA256"], "5" * 64)
        self.assertNotIn("GOOGLE_WRITER_TOKEN", env)
        self.assertEqual(env["PATH"], "/usr/local/bin:/usr/bin:/bin")

    def test_gitattributes_is_copied_into_candidate_staging_tree(self):
        with tempfile.TemporaryDirectory(prefix="pqm-gitattributes-stage-") as temporary:
            base = Path(temporary)
            source = base / "source"
            target = base / "staged"
            source.mkdir()
            content = (
                "/validation/run_c246_historical_integrity_snapshots_v1.py text eol=lf\n"
                "/validation/c246_historical_integrity_snapshots_v1.json text eol=lf\n"
            ).encode("utf-8")
            (source / ".gitattributes").write_bytes(content)

            staged = release.stage_gitattributes(source, target)

            self.assertEqual(staged, target / ".gitattributes")
            self.assertTrue(staged.is_file())
            self.assertEqual(staged.read_bytes(), content)

    def test_integrated_history_runners_are_present_in_the_delivered_test_package(self):
        manifest = release.load_package_manifest(REPOSITORY_ROOT)
        required = [
            *(f"validation/run_integrated_writer_ui_v{version}_history.py"
              for version in manifest["integrated_history_versions"]),
            *(f"validation/{name}" for name in manifest["snapshot_support_files"]),
            *(f"validation/{name}" for name in manifest["supplemental_validation_files"]),
            *(f"test_google_writer_integrated_candidate_integrity_v{version}.py"
              for version in manifest["integrity_test_versions"]),
            *(f"{manifest['integrity_manifest_dir']}/pqm_sync_ui_integrated_v{version}.json"
              for version in manifest["integrity_test_versions"]),
            *(f"validation/local_release_20260911/{name}"
              for name in manifest["required_local_release_tests"]),
            "validation/release_test_package.py",
            "validation/release_test_package_v1.json",
        ]
        for relative in required:
            with self.subTest(path=relative):
                self.assertTrue((ROOT / relative).is_file(), f"missing staged runner: {relative}")

    def test_integrated_snapshot_archives_are_available_to_the_docker_gate(self):
        package_manifest = json.loads(
            (REPOSITORY_ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )
        required = tuple(
            f"validation/fixtures/{name}"
            for name in package_manifest["release_fixture_basenames"]
            if name.startswith("pqm_sync_ui_integrated_v")
        )
        dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8")
        docker_gate = (ROOT / "validation/docker_release_gate.py").read_text(encoding="utf-8")
        dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
        self.assertIn("validation/run_local_release.py", docker_gate)
        self.assertIn("test_release_gate_infrastructure.py", docker_gate)
        self.assertIn("COPY . .", dockerfile)
        self.assertNotIn("*.zip", dockerignore)
        for relative in required:
            with self.subTest(path=relative):
                self.assertIn(Path(relative).name, package_manifest["release_fixture_basenames"])
                self.assertTrue((ROOT / relative).is_file(), f"missing immutable Docker fixture: {relative}")
                self.assertEqual((ROOT / relative).read_bytes(), (REPOSITORY_ROOT / relative).read_bytes())

    def test_staged_test_resolves_repository_root_outside_temporary_directory(self):
        with tempfile.TemporaryDirectory(prefix="pqm-release-test-root-") as temporary:
            staged_test = Path(temporary) / "test_release_gate_infrastructure.py"
            with patch.dict(os.environ, {"PQM_RELEASE_SOURCE_ROOT": str(REPOSITORY_ROOT)}):
                resolved = repository_root(staged_test)
            self.assertEqual(resolved, REPOSITORY_ROOT)
            self.assertNotEqual(staged_test.parent.resolve(), resolved)
            self.assertTrue((resolved / ".dockerignore").is_file())

    def test_docker_context_check_runs_from_a_staged_temporary_tree(self):
        with tempfile.TemporaryDirectory(prefix="pqm-docker-context-staged-test-") as temporary:
            package = Path(temporary)
            shutil.copy2(__file__, package / Path(__file__).name)
            validation = package / "validation"
            (validation / "fixtures").mkdir(parents=True)
            for relative in (
                "validation/run_local_release.py",
                "validation/docker_release_gate.py",
                "validation/document_release_history_v2.py",
                "validation/release_test_package.py",
                "validation/release_test_package_v1.json",
                "validation/run_c246_historical_integrity_snapshots_v1.py",
                "validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v3_8c6ba07.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v4_654bd0de.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v6_8e0dc78.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v7_9b3dd33.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v8_b7d8279.zip",
                "validation/fixtures/pqm_sync_ui_integrated_v9_8e74484.zip",
            ):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(REPOSITORY_ROOT / relative, target)
            environment = os.environ.copy()
            environment["PQM_RELEASE_SOURCE_ROOT"] = str(REPOSITORY_ROOT)
            result = subprocess.run(
                [sys.executable, "-B", "-m", "unittest", "-v",
                 "test_release_gate_infrastructure.ReleaseGateInfrastructureTests."
                 "test_integrated_snapshot_archives_are_available_to_the_docker_gate"],
                cwd=package,
                env=environment,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v5_historical_runner_uses_pinned_fixture_without_git(self):
        with tempfile.TemporaryDirectory(prefix="pqm-integrated-v5-no-git-") as temporary:
            package = Path(temporary)
            validation = package / "validation"
            (validation / "fixtures").mkdir(parents=True)
            runner = "validation/run_integrated_writer_ui_v5_history.py"
            fixture = "validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip"
            shutil.copy2(ROOT / runner, package / runner)
            shutil.copy2(ROOT / fixture, package / fixture)
            result = subprocess.run(
                [sys.executable, "-B", str(package / runner)],
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v7_historical_runner_uses_exact_pinned_fixture_without_git(self):
        with tempfile.TemporaryDirectory(prefix="pqm-integrated-v7-no-git-") as temporary:
            package = Path(temporary)
            validation = package / "validation"
            (validation / "fixtures").mkdir(parents=True)
            for relative in (
                "validation/run_integrated_writer_ui_v7_history.py",
                "validation/integrated_snapshot_archive.py",
                "validation/fixtures/pqm_sync_ui_integrated_v7_9b3dd33.zip",
            ):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            result = subprocess.run(
                [sys.executable, "-B", str(package / "validation/run_integrated_writer_ui_v7_history.py")],
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v8_historical_runner_uses_exact_pinned_fixture_without_git(self):
        with tempfile.TemporaryDirectory(prefix="pqm-integrated-v8-no-git-") as temporary:
            package = Path(temporary)
            for relative in (
                "validation/run_integrated_writer_ui_v8_history.py",
                "validation/integrated_snapshot_archive.py",
                "validation/fixtures/pqm_sync_ui_integrated_v8_b7d8279.zip",
            ):
                target = package / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT / relative, target)
            result = subprocess.run(
                [sys.executable, "-B", str(package / "validation/run_integrated_writer_ui_v8_history.py")],
                cwd=package,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_v5_integrity_is_excluded_from_candidate_staging_suite(self):
        class NamedTest:
            def __init__(self, test_id):
                self.test_id = test_id

            def id(self):
                return self.test_id

            def __call__(self, *args, **kwargs):
                return None

        tests = unittest.TestSuite([
            NamedTest("test_google_writer_integrated_candidate_integrity_v5.V5.test_old_snapshot"),
            NamedTest("test_release_gate_infrastructure.ReleaseGateInfrastructureTests.test_current"),
        ])
        selected = release.selected_suite(tests, "candidate")
        self.assertEqual(
            [test.id() for test in selected],
            ["test_release_gate_infrastructure.ReleaseGateInfrastructureTests.test_current"],
        )

    def test_container_release_gate_stages_missing_v2_archive_with_initialized_cwd(self):
        with tempfile.TemporaryDirectory(prefix="pqm-missing-v2-source-") as temporary:
            fake_source = Path(temporary)
            fake_validation = fake_source / "validation"
            (fake_validation / "fixtures").mkdir(parents=True)
            (fake_validation / "local_release_20260911").mkdir()
            expected_archive = fake_validation / "fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip"
            self.assertFalse(expected_archive.exists())
            expected_cwd = Path.cwd()
            with patch.object(release, "ROOT", fake_source):
                with patch.object(release, "load_package_manifest", return_value={"pinned_release_files": {}}):
                    with patch.object(release, "copy_pinned_release_file", return_value=None):
                        with patch.dict(os.environ, {"PQM_RELEASE_MODE": ""}):
                            with patch.object(sys, "argv", ["run_local_release.py", "test_nazk_workflow.py"]):
                                with patch.object(
                                    release.subprocess, "run",
                                    return_value=SimpleNamespace(returncode=1),
                                ) as run:
                                    with self.assertRaisesRegex(
                                        RuntimeError,
                                        "Integrated v2 immutable snapshot could not be staged",
                                    ):
                                        release.main()

            run.assert_called_once()
            self.assertEqual(run.call_args.kwargs["cwd"], expected_cwd)
            self.assertTrue(
                str(run.call_args.args[0][1]).endswith("run_integrated_writer_ui_v2_history.py")
            )
            self.assertEqual(
                run.call_args.kwargs["env"]["PQM_INTEGRATED_V2_ARCHIVE_OUT"],
                str(expected_archive),
            )

    def test_workflow_routes_historical_and_current_integrity_checks(self):
        workflow = (ROOT / ".github/workflows/release-checks.yml").read_text(encoding="utf-8")
        c246_runner = "validation/run_c246_historical_integrity_snapshots_v1.py"
        historical_runner = "validation/run_google_writer_historical_integrity_snapshots_v1.py"
        historical_v4 = "test_google_writer_append_continuation_integrity_v4"
        historical_apply_v5 = "test_google_writer_apply_result_integrity_v5"
        historical_apply_v6 = "test_google_writer_apply_result_integrity_v6"
        previous_apply_overlay = "test_google_writer_apply_result_integrity_v7"
        historical_apply_v9 = "test_google_writer_apply_result_integrity_v9"
        historical_continuation_v5 = "test_google_writer_append_continuation_integrity_v5"
        historical_apply_v10 = "test_google_writer_apply_result_integrity_v10"
        integrated_v1 = "test_google_writer_integrated_candidate_integrity_v1"
        previous_overlay = "test_google_writer_integrated_candidate_integrity_v3"
        previous_integrated_overlay = "test_google_writer_integrated_candidate_integrity_v5"
        previous_current_overlay = "test_google_writer_integrated_candidate_integrity_v8"
        previous_integrated_overlay_v9 = "test_google_writer_integrated_candidate_integrity_v9"
        current_overlay = "validation/v31_1/bridge.py"
        integrated_v1_runner = "validation/run_integrated_writer_ui_v1_history.py"
        integrated_v1_snapshot = "3eda8169d8dae0d76bf14b276c16e6773dd746d6"
        integrated_v2_runner = "validation/run_integrated_writer_ui_v2_history.py"
        integrated_v2_snapshot = "0d7e05984fb9b1fc7276b4cc1d8176dec383ef08"
        integrated_v3_runner = "validation/run_integrated_writer_ui_v3_history.py"
        integrated_v4_runner = "validation/run_integrated_writer_ui_v4_history.py"
        integrated_v5_runner = "validation/run_integrated_writer_ui_v5_history.py"
        integrated_v6_runner = "validation/run_integrated_writer_ui_v6_history.py"
        integrated_v7_runner = "validation/run_integrated_writer_ui_v7_history.py"
        integrated_v8_runner = "validation/run_integrated_writer_ui_v8_history.py"
        integrated_v9_runner = "validation/run_integrated_writer_ui_v9_history.py"
        integrated_v10_runner = "validation/run_integrated_writer_ui_v10_history.py"
        integrated_v11_runner = "validation/run_integrated_writer_ui_v11_history.py"
        integrated_v12_runner = "validation/run_integrated_writer_ui_v12_history.py"
        integrated_v13_runner = "validation/run_integrated_writer_ui_v13_history.py"
        integrated_v14_runner = "validation/run_integrated_writer_ui_v14_history.py"
        integrated_v15_runner = "validation/run_integrated_writer_ui_v15_history.py"
        integrated_v16_runner = "validation/run_integrated_writer_ui_v16_history.py"
        integrated_v17_runner = "validation/run_integrated_writer_ui_v17_history.py"
        integrated_v18_runner = "validation/run_integrated_writer_ui_v18_history.py"
        integrated_v19_runner = "validation/run_integrated_writer_ui_v19_history.py"
        integrated_v20_runner = "validation/run_integrated_writer_ui_v20_history.py"
        integrated_v21_runner = "validation/run_integrated_writer_ui_v21_history.py"
        integrated_v22_runner = "validation/run_integrated_writer_ui_v22_history.py"
        integrated_v23_runner = "validation/run_integrated_writer_ui_v23_history.py"
        integrated_v24_runner = "validation/run_integrated_writer_ui_v24_history.py"
        integrated_v25_runner = "validation/run_integrated_writer_ui_v25_history.py"
        integrated_v27_runner = "validation/run_integrated_writer_ui_v27_history.py"
        integrated_v28_runner = "validation/run_integrated_writer_ui_v28_history.py"
        integrated_v4_snapshot = "654bd0de0e5b3de6be61c5293a9fc00cf17217c3"
        integrated_v3_snapshot = "8c6ba07372196b1919a88beb7da3078e6c53d4d0"
        direct_historical_test = "python -B -m unittest -v test_legacy_reconciliation_evidence_v2_integrity"

        self.assertIn("node --test", workflow)
        self.assertIn("validation/edr_monitoring_drawer.test.cjs", workflow)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/partial-reconciliation.test.cjs", workflow)
        self.assertIn("scripts/pqm-google-writer/mirror-alignment/sandbox/legacy-reconciliation-evidence-v2.test.cjs", workflow)
        self.assertIn("fetch-depth: 0", workflow)
        self.assertIn("python -m venv \"$RUNNER_TEMP/pqm-release-python\"", workflow)
        self.assertIn("pip install --disable-pip-version-check -r requirements.txt", workflow)
        self.assertIn("$RUNNER_TEMP/pqm-release-python/bin/python\" -B validation/run_c246_historical_integrity_snapshots_v1.py", workflow)
        self.assertIn("git archive ce722e3ed654a0e30be3b048a292e1e7e6ba0828", workflow)
        self.assertIn("git archive 2a4e4bff0bbbe84670d3bb10a5ba4b90347a7d78", workflow)
        self.assertIn("test_google_writer_append_continuation_integrity_v2", workflow)
        self.assertIn("test_google_writer_append_continuation_integrity_v3", workflow)
        self.assertIn("test_google_writer_update_append_v2_integrity", workflow)
        self.assertIn("test_google_writer_update_append_v3_integrity", workflow)
        self.assertIn(c246_runner, workflow)
        self.assertIn(historical_runner, workflow)
        self.assertIn(historical_v4, workflow)
        self.assertIn(historical_apply_v5, workflow)
        self.assertIn(historical_apply_v6, workflow)
        self.assertIn("git archive 86b6ad82105fdcd7fa530a872943525af812ec47", workflow)
        self.assertIn("git archive 8bf5fb0188bebf6f2b35583ec018848c914b714c", workflow)
        self.assertIn("git archive 926ae60ff3412a9c236c903b70623881459d871c", workflow)
        self.assertIn("git archive b988f140af37c45bd5461735cf40d18cd00d741a", workflow)
        self.assertIn("git archive 9b38a258c0d279f33541dac6e95d12d3057a9b70", workflow)
        self.assertIn(previous_apply_overlay, workflow)
        self.assertIn(historical_apply_v9, workflow)
        self.assertIn(historical_continuation_v5, workflow)
        self.assertIn(historical_apply_v10, workflow)
        self.assertIn(integrated_v1_runner, workflow)
        self.assertIn(integrated_v2_runner, workflow)
        self.assertIn(integrated_v3_runner, workflow)
        self.assertIn(integrated_v4_runner, workflow)
        self.assertIn(integrated_v5_runner, workflow)
        self.assertIn(integrated_v6_runner, workflow)
        self.assertIn(integrated_v7_runner, workflow)
        self.assertIn(integrated_v8_runner, workflow)
        self.assertIn(integrated_v9_runner, workflow)
        self.assertIn(integrated_v10_runner, workflow)
        self.assertIn(integrated_v11_runner, workflow)
        self.assertIn(integrated_v12_runner, workflow)
        self.assertIn(integrated_v13_runner, workflow)
        self.assertIn(integrated_v14_runner, workflow)
        self.assertIn(integrated_v15_runner, workflow)
        self.assertIn(integrated_v16_runner, workflow)
        self.assertIn(integrated_v17_runner, workflow)
        self.assertIn(integrated_v18_runner, workflow)
        self.assertIn(integrated_v19_runner, workflow)
        self.assertIn(integrated_v20_runner, workflow)
        self.assertIn(integrated_v21_runner, workflow)
        self.assertIn(integrated_v22_runner, workflow)
        self.assertIn(integrated_v23_runner, workflow)
        self.assertIn(integrated_v24_runner, workflow)
        self.assertIn(integrated_v25_runner, workflow)
        self.assertIn(integrated_v27_runner, workflow)
        self.assertIn(integrated_v28_runner, workflow)
        for token in (
            "run_integrated_writer_ui_v27_candidate_history.py",
            "run_integrated_writer_ui_v28_candidate_history.py",
            "run_integrated_writer_ui_v29_history.py",
            "run_integrated_writer_ui_v30_history.py",
            "PQM_INTEGRATED_V127_SNAPSHOT_ARCHIVE",
            "PQM_INTEGRATED_V128_SNAPSHOT_ARCHIVE",
            "PQM_INTEGRATED_V29_SNAPSHOT_ARCHIVE",
            "PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE",
            "PQM_UPDATE_APPEND_V2_V26_FULL_ARCHIVE",
        ):
            self.assertIn(token, workflow)
        self.assertIn('PQM_INTEGRATED_V22_SNAPSHOT_ARCHIVE_OUT="$RUNNER_TEMP/pqm-integrated-v22-snapshot.zip"', workflow)
        self.assertIn('PQM_INTEGRATED_V22_SNAPSHOT_ARCHIVE_SHA256', workflow)
        self.assertIn('PQM_INTEGRATED_V22_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v22-snapshot.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V22_SNAPSHOT_ARCHIVE_SHA256="$PQM_INTEGRATED_V22_SNAPSHOT_ARCHIVE_SHA256"', workflow)
        self.assertIn('PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE_OUT="$RUNNER_TEMP/pqm-integrated-v23-snapshot.zip"', workflow)
        self.assertIn('PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE_SHA256', workflow)
        self.assertIn('PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v23-snapshot.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE_SHA256="$PQM_INTEGRATED_V23_SNAPSHOT_ARCHIVE_SHA256"', workflow)
        self.assertIn('PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_OUT="$RUNNER_TEMP/pqm-integrated-v24-snapshot.zip"', workflow)
        self.assertIn('PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_SHA256', workflow)
        self.assertIn('PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v24-snapshot.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_SHA256="$PQM_INTEGRATED_V24_SNAPSHOT_ARCHIVE_SHA256"', workflow)
        self.assertIn('PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE_OUT="$RUNNER_TEMP/pqm-integrated-v30-candidate-snapshot.zip"', workflow)
        self.assertIn('PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE_SHA256', workflow)
        self.assertIn('PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v30-candidate-snapshot.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE_SHA256="$PQM_INTEGRATED_V30_SNAPSHOT_ARCHIVE_SHA256"', workflow)
        self.assertIn('dst=/tmp/pqm-integrated-v24-snapshot.zip,readonly', workflow)
        self.assertIn('PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_OUT="$RUNNER_TEMP/pqm-integrated-v25-snapshot.zip"', workflow)
        self.assertIn('PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_SHA256', workflow)
        self.assertIn('PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v25-snapshot.zip', workflow)
        self.assertIn('PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_SHA256="$PQM_INTEGRATED_V25_SNAPSHOT_ARCHIVE_SHA256"', workflow)
        self.assertIn('dst=/tmp/pqm-integrated-v25-snapshot.zip,readonly', workflow)
        for version in ("V1", "V2", "V3", "V4"):
            self.assertNotIn(f"PQM_INTEGRATED_{version}_ARCHIVE_OUT=validation/fixtures/", workflow)
        self.assertIn(
            "test_release_gate_infrastructure.ReleaseGateInfrastructureTests."
            "test_container_release_gate_stages_missing_v2_archive_with_initialized_cwd", workflow
        )
        self.assertIn(current_overlay, workflow)
        self.assertIn("validation.local_release_20260911.test_uo_work_queue_http", workflow)
        current_integrity_run = workflow.split(
            'document_release_history_v2.py -v \\\n', 1
        )[1].split("--mount", 1)[0]
        self.assertIsNone(re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(previous_overlay)}(?![A-Za-z0-9_])",
            current_integrity_run,
        ))
        self.assertNotIn(direct_historical_test, workflow)
        self.assertLess(workflow.index(c246_runner), workflow.index(historical_runner))
        self.assertLess(workflow.index(historical_apply_v5), workflow.index(historical_runner))
        self.assertLess(workflow.index(historical_runner), workflow.index(historical_apply_v6))
        self.assertLess(workflow.index(historical_apply_v6), workflow.index(previous_apply_overlay))
        self.assertIn("test_google_writer_apply_result_integrity_v8)", workflow)
        self.assertLess(workflow.index(previous_apply_overlay), workflow.index("test_google_writer_apply_result_integrity_v8)"))
        self.assertLess(workflow.index("test_google_writer_apply_result_integrity_v8)"), workflow.index(historical_apply_v9))
        self.assertLess(workflow.index(historical_apply_v9), workflow.index(historical_continuation_v5))
        self.assertLess(workflow.index(historical_continuation_v5), workflow.index(historical_apply_v10))
        self.assertLess(workflow.index(historical_apply_v10), workflow.index(integrated_v1_runner))
        self.assertLess(workflow.index(integrated_v1_runner), workflow.index(integrated_v2_runner))
        self.assertLess(workflow.index(integrated_v2_runner), workflow.index(integrated_v3_runner))
        self.assertLess(workflow.index(integrated_v3_runner), workflow.index(integrated_v4_runner))
        self.assertLess(workflow.index(integrated_v4_runner), workflow.index(integrated_v5_runner))
        self.assertLess(workflow.index(integrated_v5_runner), workflow.index(integrated_v6_runner))
        self.assertLess(workflow.index(integrated_v6_runner), workflow.index(integrated_v7_runner))
        self.assertLess(workflow.index(integrated_v7_runner), workflow.index(integrated_v8_runner))
        self.assertLess(workflow.index(integrated_v8_runner), workflow.index(integrated_v9_runner))
        self.assertLess(workflow.index(integrated_v17_runner), workflow.index(integrated_v18_runner))
        self.assertLess(workflow.index(integrated_v18_runner), workflow.index(integrated_v19_runner))
        self.assertLess(workflow.index(integrated_v19_runner), workflow.index(integrated_v20_runner))
        self.assertLess(workflow.index(integrated_v20_runner), workflow.index(integrated_v21_runner))
        self.assertLess(workflow.index(integrated_v21_runner), workflow.index(integrated_v22_runner))
        self.assertLess(workflow.index(integrated_v22_runner), workflow.index(integrated_v23_runner))
        self.assertLess(workflow.index(integrated_v23_runner), workflow.index(integrated_v24_runner))
        self.assertLess(workflow.index(integrated_v24_runner), workflow.index(integrated_v25_runner))
        self.assertLess(workflow.index(integrated_v25_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(integrated_v10_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(integrated_v11_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(integrated_v12_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(integrated_v13_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(integrated_v14_runner), workflow.index(current_overlay))
        self.assertLess(workflow.index(integrated_v15_runner), workflow.index(current_overlay))
        self.assertIn("PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V11_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V12_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V13_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V14_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V15_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V16_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V17_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V18_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V19_SNAPSHOT_ARCHIVE_OUT", workflow)
        self.assertIn("PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V11_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V12_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V13_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V14_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V15_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V16_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V17_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V18_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V19_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v10-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v11-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v12-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v13-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v14-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v15-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v16-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v17-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v18-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v19-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v20-snapshot.zip,readonly", workflow)
        self.assertIn("dst=/tmp/pqm-integrated-v21-snapshot.zip,readonly", workflow)
        self.assertIn("PQM_INTEGRATED_V20_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertIn("PQM_INTEGRATED_V21_SNAPSHOT_ARCHIVE_SHA256", workflow)
        self.assertNotIn("COPY .git", workflow)
        current_step = _validated_v31_workflow_step(workflow)
        run_lines = current_step["run"].splitlines()
        route_index = next(index for index, line in enumerate(run_lines)
                           if V31_GITHUB_ROUTE in line)
        current_integrity_command = "\n".join(run_lines[route_index:])
        self.assertIn(current_overlay, current_integrity_command)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v24", current_integrity_command)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v25", current_integrity_command)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v26", current_integrity_command)
        self.assertNotIn("test_google_writer_integrated_candidate_integrity_v27", current_integrity_command)
        self.assertIn("validation.local_release_20260911.test_integrated_snapshot_staging", current_integrity_command)
        self.assertIn("validation.local_release_20260911.test_release_test_package", current_integrity_command)
        self.assertNotRegex(
            current_integrity_command,
            r"test_google_writer_integrated_candidate_integrity_v[1-9](?![0-9])",
        )
        self.assertNotIn(previous_integrated_overlay_v9, current_integrity_command)
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))

        snapshot_route = workflow.split('writer_v5_v10_snapshot=', 1)[1].split(integrated_v1_runner, 1)[0]
        self.assertIn('git archive 9b38a258c0d279f33541dac6e95d12d3057a9b70', snapshot_route)
        self.assertIn('(cd "$writer_v5_v10_snapshot"', snapshot_route)
        self.assertIn(historical_continuation_v5, snapshot_route)
        self.assertIn(historical_apply_v10, snapshot_route)
        self.assertNotIn(current_overlay, snapshot_route)
        self.assertNotIn(integrated_v1, snapshot_route)
        self.assertLess(workflow.index(current_overlay), workflow.index("Install Playwright and Chromium"))

        runner = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        integrated_history_runner = (ROOT / integrated_v1_runner).read_text(encoding="utf-8")
        integrated_v2_history_runner = (ROOT / integrated_v2_runner).read_text(encoding="utf-8")
        self.assertIn(integrated_v1_snapshot, integrated_history_runner)
        self.assertIn("git', 'archive', '--format=zip'", integrated_history_runner)
        self.assertIn(integrated_v1, integrated_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v1_3eda816.zip')", integrated_history_runner)
        self.assertIn(integrated_v2_snapshot, integrated_v2_history_runner)
        self.assertIn("'git', 'archive', '--format=zip'", integrated_v2_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v2", integrated_v2_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v2_0d7e059.zip')", integrated_v2_history_runner)
        integrated_v3_history_runner = (ROOT / integrated_v3_runner).read_text(encoding="utf-8")
        self.assertIn(integrated_v3_snapshot, integrated_v3_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v3", integrated_v3_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v3_8c6ba07.zip')", integrated_v3_history_runner)
        integrated_v4_history_runner = (ROOT / integrated_v4_runner).read_text(encoding="utf-8")
        self.assertIn(integrated_v4_snapshot, integrated_v4_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v4", integrated_v4_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v4_654bd0de.zip')", integrated_v4_history_runner)
        integrated_v5_history_runner = (ROOT / integrated_v5_runner).read_text(encoding="utf-8")
        self.assertIn("cd01e1376114781e43d408b5b83ee15e22050a53", integrated_v5_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v5", integrated_v5_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v5_cd01e13.zip')", integrated_v5_history_runner)
        integrated_v6_history_runner = (ROOT / integrated_v6_runner).read_text(encoding="utf-8")
        self.assertIn("8e0dc787d0d1db8211fefcf531f722508d3d2d74", integrated_v6_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v6", integrated_v6_history_runner)
        self.assertIn("ARCHIVE_RELATIVE = Path('validation/fixtures/pqm_sync_ui_integrated_v6_8e0dc78.zip')", integrated_v6_history_runner)
        integrated_v7_history_runner = (ROOT / integrated_v7_runner).read_text(encoding="utf-8")
        self.assertIn("test_google_writer_integrated_candidate_integrity_v7", integrated_v7_history_runner)
        self.assertIn("pqm_sync_ui_integrated_v7_9b3dd33.zip", integrated_v7_history_runner)
        integrated_v8_history_runner = (ROOT / integrated_v8_runner).read_text(encoding="utf-8")
        self.assertIn("b7d8279ab8616553140ce7012685242631f6b1c3", integrated_v8_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v8", integrated_v8_history_runner)
        self.assertIn("pqm_sync_ui_integrated_v8_b7d8279.zip", integrated_v8_history_runner)
        integrated_v9_history_runner = (ROOT / integrated_v9_runner).read_text(encoding="utf-8")
        self.assertIn("8e74484d3961b70355a4868c72336e22fad9d8de", integrated_v9_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v9", integrated_v9_history_runner)
        integrated_v10_history_runner = (ROOT / integrated_v10_runner).read_text(encoding="utf-8")
        integrated_v11_history_runner = (ROOT / integrated_v11_runner).read_text(encoding="utf-8")
        integrated_v12_history_runner = (ROOT / integrated_v12_runner).read_text(encoding="utf-8")
        integrated_v13_history_runner = (ROOT / integrated_v13_runner).read_text(encoding="utf-8")
        integrated_v14_history_runner = (ROOT / integrated_v14_runner).read_text(encoding="utf-8")
        integrated_v15_history_runner = (ROOT / integrated_v15_runner).read_text(encoding="utf-8")
        integrated_v16_history_runner = (ROOT / integrated_v16_runner).read_text(encoding="utf-8")
        self.assertIn("snapshot_archive_for_runner", integrated_v10_history_runner)
        self.assertIn("snapshot_archive_for_runner", integrated_v11_history_runner)
        self.assertIn("27f28b501d37ce125e2334af769f2d23f33355b5", integrated_v10_history_runner)
        self.assertIn("b2804d6e20e6b81b128508f285eb71e807f01ddf", integrated_v11_history_runner)
        self.assertIn("PQM_INTEGRATED_V10_SNAPSHOT_ARCHIVE", integrated_v10_history_runner + workflow)
        self.assertIn("PQM_INTEGRATED_V11_SNAPSHOT_ARCHIVE", integrated_v11_history_runner + workflow)
        self.assertIn("snapshot_archive_for_runner", integrated_v12_history_runner)
        self.assertIn("f8def8951eb9f95f1a5139bd7138681c4c1a9d7b", integrated_v12_history_runner)
        self.assertIn("PQM_INTEGRATED_V12_SNAPSHOT_ARCHIVE", integrated_v12_history_runner + workflow)
        self.assertIn("snapshot_archive_for_runner", integrated_v13_history_runner)
        self.assertIn("f64c017e33ad46457f40a8ab0140f86db6edf11c", integrated_v13_history_runner)
        self.assertIn("PQM_INTEGRATED_V13_SNAPSHOT_ARCHIVE", integrated_v13_history_runner + workflow)
        self.assertIn("snapshot_archive_for_runner", integrated_v14_history_runner)
        self.assertIn("766d1ed9354e1af56e19d50d50c818ff701dd85e", integrated_v14_history_runner)
        self.assertIn("version=14", integrated_v14_history_runner)
        self.assertIn("24ebc7786cfe49722b9427eea5425102f5697198aecbbc83dfd156c1a226d727", integrated_v14_history_runner)
        self.assertIn("PQM_INTEGRATED_V14_SNAPSHOT_ARCHIVE", integrated_v14_history_runner + workflow)
        self.assertIn("snapshot_archive_for_runner", integrated_v15_history_runner)
        self.assertIn("86fe0d85bc36f431af6708918c07add73144f9db", integrated_v15_history_runner)
        self.assertIn("version=15", integrated_v15_history_runner)
        self.assertIn("5097d801488b83b4bcae85650d7074ea1a13e755e390880258eb382ce0378977", integrated_v15_history_runner)
        self.assertIn("PQM_INTEGRATED_V15_SNAPSHOT_ARCHIVE", integrated_v15_history_runner + workflow)
        self.assertIn("snapshot_archive_for_runner", integrated_v16_history_runner)
        self.assertIn("f5f2fd712eeae1b33e3dac719fa6463c70f1e253", integrated_v16_history_runner)
        self.assertIn("version=16", integrated_v16_history_runner)
        self.assertIn("859050d7353edf2d776679ce7a12b0cbbd158f7b1a314e2a88234422a5699488", integrated_v16_history_runner)
        self.assertIn("PQM_INTEGRATED_V16_SNAPSHOT_ARCHIVE", integrated_v16_history_runner + workflow)
        self.assertIn("'test_legacy_reconciliation_evidence_v2_integrity'", runner)
        self.assertIn("c246 contracts are run by the mandatory workflow snapshot step", runner)
        self.assertNotIn("run_c246_historical_integrity_snapshots_v1.py", runner)
        self.assertIn("run_google_writer_historical_integrity_snapshots_v1.py", runner)
        self.assertNotIn("'test_google_writer_apply_result_diagnostic'", runner.split("HISTORICAL_INTEGRITY_MODULES", 1)[1].split("}\nEXACT_TREE_OVERLAY_MODULES", 1)[0])
        historical_modules = runner.split("HISTORICAL_INTEGRITY_MODULES", 1)[1].split("}\nEXACT_TREE_OVERLAY_MODULES", 1)[0]
        self.assertNotIn("'test_google_writer_integrated_candidate_integrity_v1'", historical_modules)
        self.assertNotIn("'test_google_writer_append_continuation_integrity_v2'", historical_modules)
        self.assertNotIn("'test_google_writer_append_continuation_integrity_v3'", historical_modules)
        exact_modules = runner.split("EXACT_TREE_OVERLAY_MODULES", 1)[1].split("}", 1)[0]
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v1'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v2'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v3'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v4'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v6'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v7'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v8'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v9'", exact_modules)
        self.assertIn("'test_google_writer_integrated_candidate_integrity_v10'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v2'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v3'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v4'", exact_modules)
        self.assertIn("'test_google_writer_append_continuation_integrity_v5'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v5'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v6'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v7'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v8'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v9'", exact_modules)
        self.assertIn("'test_google_writer_apply_result_integrity_v10'", exact_modules)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v2", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v3", runner)
        self.assertIn("run_integrated_writer_ui_v1_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v2_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v3_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v4_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v5_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v6", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v9", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v10", runner)
        self.assertIn("run_integrated_writer_ui_v6_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v7_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v8_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v10_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v11_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v12", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v13", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v14", integrated_v14_history_runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v15", runner)
        self.assertIn("run_integrated_writer_ui_v15_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v16_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v17_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v18_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v16", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v17", runner)
        self.assertIn("run_integrated_writer_ui_v20_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v21_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v22_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v25", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v26", runner)
        self.assertIn("run_integrated_writer_ui_v25_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v24_history.py", runner)
        self.assertIn("integrated_v24_history", runner)
        self.assertIn("integrated_v25_history", runner)
        self.assertIn("integrated_v26_history", runner)
        self.assertIn("integrated_v27_history", runner)
        self.assertIn("integrated_v28_history", runner)
        self.assertIn("integrated_v27_candidate_history", runner)
        self.assertIn("integrated_v28_candidate_history", runner)
        self.assertIn("integrated_v29_candidate_history", runner)
        self.assertIn("integrated_v30_history", runner)
        self.assertIn("integrated_v31_current", runner)
        self.assertIn("background_exceptions.report()", runner)
        self.assertIn("release_subprocess_environment", runner)
        self.assertIn("run_integrated_writer_ui_v27_history.py", runner)
        self.assertIn("run_integrated_writer_ui_v30_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v28", runner)
        self.assertIn("run_integrated_writer_ui_v26_history.py", runner)
        self.assertIn("test_google_writer_integrated_candidate_integrity_v27", runner)
        self.assertIn("run_integrated_writer_ui_v23_history.py", runner)
        package_manifest = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )
        self.assertIn("integrated_snapshot_archive.py", package_manifest["snapshot_support_files"])
        for fixture in (
            "pqm_sync_ui_integrated_v1_3eda816.zip",
            "pqm_sync_ui_integrated_v2_0d7e059.zip",
            "pqm_sync_ui_integrated_v4_654bd0de.zip",
            "pqm_sync_ui_integrated_v5_cd01e13.zip",
            "pqm_sync_ui_integrated_v7_9b3dd33.zip",
            "pqm_sync_ui_integrated_v8_b7d8279.zip",
        ):
            self.assertIn(fixture, package_manifest["release_fixture_basenames"])
        self.assertIn(previous_current_overlay, integrated_v8_history_runner)
        self.assertIn("node validation/uo_work_page_layout_browser.cjs", workflow)
        self.assertIn("npm install --prefix \"$RUNNER_TEMP/pqm-playwright\"", workflow)
        self.assertIn('node_modules/.bin/playwright" install --with-deps chromium', workflow)
        self.assertIn("validation/queue_statistics_ui.test.cjs", workflow)
        browser_block = workflow.split("- name: Run Appeals browser regressions", 1)[1].split("- name:", 1)[0]
        self.assertIn("node validation/uo_work_page_layout_browser.cjs", browser_block)
        self.assertIn("PQM_INTEGRATED_V14_SNAPSHOT_ARCHIVE=/tmp/pqm-integrated-v14-snapshot.zip", workflow)
        self.assertNotIn("'test_google_writer_update_append_v2_integrity'", exact_modules)
        self.assertNotIn("'test_google_writer_update_append_v3_integrity'", exact_modules)
        self.assertNotIn("'test_google_writer_apply_result_diagnostic'", exact_modules)
        self.assertIn("test_google_writer_apply_result_integrity_v7", workflow)
        self.assertIn("test_google_writer_apply_result_integrity_v8", workflow)
        self.assertIn("test_google_writer_saved_continuation_audit", workflow)
        browser_runner = (ROOT / "validation/google_writer_preview_modal_browser.cjs").read_text(encoding="utf-8")
        self.assertIn("validation/google_writer_apply_result_ui.test.cjs", browser_runner)
        self.assertIn("node validation/google_writer_preview_modal_browser.cjs", workflow)
        layout_runner = (ROOT / "validation/google_writer_apply_modal_layout_browser.cjs").read_text(encoding="utf-8")
        self.assertIn("innerWidth", layout_runner)
        self.assertIn("footer stays fixed while scrolling", layout_runner)
        self.assertIn("node validation/google_writer_apply_modal_layout_browser.cjs", workflow)

    def test_integrated_v9_history_archive_mutation_is_rejected(self):
        manifest_path = ROOT / "validation/local_release_20261116/pqm_sync_ui_integrated_v10.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        fixture_relative = "validation/fixtures/pqm_sync_ui_integrated_v9_8e74484.zip"
        expected_sha = manifest["files"][fixture_relative]
        archive = (ROOT / fixture_relative).read_bytes()
        self.assertTrue(archive)
        mutated = archive[:-1] + bytes([archive[-1] ^ 1])
        helper_path = REPOSITORY_ROOT / "validation/integrated_snapshot_archive.py"
        spec = importlib.util.spec_from_file_location("pqm_integrated_snapshot_archive", helper_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        with self.assertRaisesRegex(helper.SnapshotArchiveError, "fixture ZIP SHA mismatch"):
            helper.verify_fixture_sha256(mutated, expected_sha, "deliberately mutated v9 history")

    def test_c246_route_manifest_is_pinned_and_covers_all_historical_modules_once(self):
        manifest_path = ROOT / "validation/c246_historical_integrity_snapshots_v1.json"
        raw = manifest_path.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), c246_snapshots.MANIFEST_SHA256)
        manifest = c246_snapshots.load_manifest()
        modules = [test["module"] for route in manifest["routes"] for test in route["tests"]]
        self.assertEqual(len(modules), 16)
        self.assertEqual(len(set(modules)), len(modules))
        self.assertEqual(
            set(modules),
            {
                "test_google_sandbox_baseline_compatibility", "test_halloween_motion_integration",
                "test_sandbox_personal_theme", "test_sandbox_appeals_scenario_api_integrity",
                "test_sandbox_appeals_scenario_readonly_integrity", "test_sandbox_nazk_scroll_integrity",
                "test_sandbox_dst_hotfix_integrity", "test_sandbox_nazk_appeals_stabilization_integrity",
                "test_sandbox_nazk_appeals_stabilization_v3_integrity",
                "test_sandbox_nazk_appeals_stabilization_v4_integrity",
                "test_sandbox_nazk_appeals_stabilization_v5_integrity",
                "test_sandbox_nazk_recovery_integrity", "test_sandbox_nazk_recovery_qualification_integrity",
                "test_sandbox_nazk_columns_integrity", "test_sandbox_nazk_preview_integrity",
                "test_sandbox_ui_integrated_d457_integrity",
            },
        )
        routes_by_commit = {route["commit"]: {test["module"] for test in route["tests"]}
                            for route in manifest["routes"]}
        self.assertEqual(routes_by_commit, {
            "b2027e6d687bc4018a2720f10fae228ccff7b201": {
                "test_google_sandbox_baseline_compatibility", "test_halloween_motion_integration"},
            "fbcce44cecf0923e4818ddeab269e478fe73939d": {"test_sandbox_personal_theme"},
            "b529ae3648f30708df23c87c9603d2bf45df6ac9": {
                "test_sandbox_appeals_scenario_api_integrity", "test_sandbox_appeals_scenario_readonly_integrity",
                "test_sandbox_nazk_scroll_integrity"},
            "990483222f7e65517befc285516a9d80aee2580d": {"test_sandbox_dst_hotfix_integrity"},
            "f6070a003c2442558303cfd9692d68cc6dfc268e": {"test_sandbox_nazk_appeals_stabilization_integrity"},
            "c246edefaa676d137d3f38d40f18d039f7b5bac2": {
                "test_sandbox_nazk_appeals_stabilization_v3_integrity",
                "test_sandbox_nazk_appeals_stabilization_v4_integrity",
                "test_sandbox_nazk_appeals_stabilization_v5_integrity",
                "test_sandbox_nazk_recovery_integrity", "test_sandbox_nazk_recovery_qualification_integrity"},
            "a168b61506fbde4f7a8d8bb80bbb40a98d6073f0": {"test_sandbox_nazk_columns_integrity"},
            "af8202b4e968f09e55ac5c6855ad29a6f2c05bc1": {"test_sandbox_nazk_preview_integrity"},
            "bddd5f6515f594304162e99e203fa82ece065cbf": {"test_sandbox_ui_integrated_d457_integrity"},
        })
        self.assertEqual(len(manifest["routes"]), 9)
        archived_routes = [route for route in manifest["routes"] if "archive" in route]
        self.assertEqual(len(archived_routes), 1)
        self.assertEqual(archived_routes[0]["archive_sha256"],
                         "e0931cc43d5c99a001771fdd12ef5bea6a87003400a458c9a3f197372671c865")

    def test_c246_snapshot_materialization_fails_closed_on_missing_commit_and_bad_pins(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.name", "Snapshot Test"], check=True)
            subprocess.run(["git", "-C", str(repo), "config", "user.email", "snapshot-test@example.invalid"], check=True)
            (repo / "test_example_integrity.py").write_bytes(b"# exact historical test\n")
            subprocess.run(["git", "-C", str(repo), "add", "test_example_integrity.py"], check=True)
            subprocess.run(["git", "-C", str(repo), "commit", "-qm", "snapshot fixture"], check=True)
            commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
            tree = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD^{tree}"], text=True).strip()
            test_hash = hashlib.sha256((repo / "test_example_integrity.py").read_bytes()).hexdigest()
            route = {"commit": commit, "tree": tree, "tests": [{
                "module": "test_example_integrity", "path": "test_example_integrity.py", "sha256": test_hash,
            }]}
            snapshot_root = root / "snapshot"
            c246_snapshots.materialize_snapshot(repo, route, snapshot_root)
            self.assertEqual((snapshot_root / "test_example_integrity.py").read_bytes(), b"# exact historical test\n")

            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_snapshot(repo, {**route, "commit": "0" * 40}, root / "missing-commit")
            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_snapshot(repo, {**route, "tree": "0" * 40}, root / "wrong-tree")
            bad_test = {**route, "tests": [{**route["tests"][0], "sha256": "0" * 64}]}
            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_snapshot(repo, bad_test, root / "wrong-test-hash")

    def test_c246_offline_historical_copy_is_pinned_to_the_exact_git_tree(self):
        manifest = c246_snapshots.load_manifest()
        route = next(route for route in manifest["routes"] if route["commit"].startswith("af8202b"))
        archive = ROOT / route["archive"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            empty_git = root / "no-git-history"
            empty_git.mkdir()
            materialized = root / "materialized"
            materialized.mkdir()
            code, count = c246_snapshots.run_route(empty_git, route, materialized)
            self.assertEqual((code, count), (0, 1))
            snapshot_root = materialized / route["commit"]
            self.assertTrue((snapshot_root / "test_sandbox_nazk_preview_integrity.py").is_file())
            self.assertTrue((snapshot_root / "validation/fixtures/nazk_preview_baseline_f394d4c.zip").is_file())
            with self.assertRaises(c246_snapshots.SnapshotError):
                c246_snapshots.materialize_archived_snapshot(
                    archive, "0" * 64, route, Path(tmp) / "corrupt")

    def test_historical_fixture_staging_uses_authentic_fixture_only_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            historic = root / "historic"
            infrastructure = root / "infrastructure"
            old_fixture = historic / "validation/fixtures" / "snapshot.zip"
            pinned_fixture = infrastructure / "validation/fixtures" / "snapshot.zip"
            old_fixture.parent.mkdir(parents=True)
            pinned_fixture.parent.mkdir(parents=True)
            old_fixture.write_bytes(b"historical-source-fixture")
            pinned_fixture.write_bytes(b"pinned-fixture")
            self.assertEqual(release.release_fixture_source(historic, infrastructure, "snapshot.zip", "historical_integrity"), old_fixture)

            old_fixture.unlink()
            self.assertEqual(release.release_fixture_source(historic, infrastructure, "snapshot.zip", "historical_integrity"), pinned_fixture)
            self.assertEqual(release.release_fixture_source(historic, infrastructure, "snapshot.zip", "candidate"), old_fixture)
            with self.assertRaises(ValueError):
                release.release_fixture_source(historic, infrastructure, "../server.py", "historical_integrity")

    def test_windows_sqlite_uri_is_normalized_without_changing_mode_or_other_uris(self):
        normalized = release.normalize_windows_sqlite_uri(r"file:C:\pqm-test\db.sqlite3?mode=ro")
        self.assertTrue(normalized.startswith("file:///"))
        self.assertTrue(normalized.endswith("?mode=ro"))
        self.assertEqual(release.normalize_windows_sqlite_uri("file:relative.sqlite3?mode=ro"),
                         "file:relative.sqlite3?mode=ro")
        self.assertEqual(release.normalize_windows_sqlite_uri("file:///tmp/pqm-test.sqlite3?mode=ro"),
                         "file:///tmp/pqm-test.sqlite3?mode=ro")
        self.assertEqual(release.normalize_windows_sqlite_uri(":memory:"), ":memory:")

    def test_historical_snapshot_ledger_is_complete_and_archive_hashes_match(self):
        ledger_path = ROOT / "validation/google_writer_historical_integrity_snapshots_v1.json"
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        archive_path = ROOT / ledger["archive"]
        self.assertEqual(hashlib.sha256(archive_path.read_bytes()).hexdigest(), ledger["archive_sha256"])
        self.assertGreaterEqual(len(ledger["snapshots"]), 11)
        with zipfile.ZipFile(archive_path) as archive:
            self.assertIsNone(archive.testzip())
            names = set(archive.namelist())
            for snapshot_id, snapshot in ledger["snapshots"].items():
                prefix = f"snapshots/{snapshot_id}/"
                self.assertIn(prefix + snapshot["test"], names)
                self.assertTrue(snapshot["commit"].startswith(tuple("0123456789abcdef")))
                self.assertEqual({name[len(prefix):] for name in names if name.startswith(prefix)},
                                 set(snapshot["files"]))
                for relative, expected in snapshot["files"].items():
                    with self.subTest(snapshot=snapshot_id, path=relative):
                        self.assertEqual(hashlib.sha256(archive.read(prefix + relative)).hexdigest(), expected)

    def test_historical_runner_fails_closed_instead_of_falling_back_to_current_files(self):
        runner = (ROOT / "validation/run_google_writer_historical_integrity_snapshots_v1.py").read_text(encoding="utf-8")
        self.assertIn("snapshot ledger missing; refusing candidate-source fallback", runner)
        self.assertIn("snapshot archive missing; refusing candidate-source fallback", runner)
        harness = (ROOT / "validation/run_local_release.py").read_text(encoding="utf-8")
        package_manifest = json.loads(
            (ROOT / "validation/release_test_package_v1.json").read_text(encoding="utf-8")
        )
        self.assertIn("run_google_writer_historical_integrity_snapshots_v1.py", harness)
        self.assertIn("google_writer_historical_integrity_snapshots_v1_compact.zip",
                      package_manifest["release_fixture_basenames"])
        self.assertIn("validation/google_writer_historical_integrity_snapshots_v1.json",
                      package_manifest["infrastructure_auxiliary_files"])
        self.assertIn("PQM_RELEASE_INFRA_ROOT", harness)
        self.assertIn("Path(__file__).resolve().parents[1]).resolve()", harness)
        self.assertIn("sandbox_runtime_messages_integrated_v1_86ea864.py",
                      package_manifest["root_level_release_files"])


if __name__ == "__main__":
    unittest.main()
