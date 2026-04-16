# -*- coding: utf-8 -*-

import glob
import json
import os
import subprocess
import sys
import textwrap
import unittest

try:
    from unittest import mock
except ImportError:
    import mock

from nplusone.core.report import Report
from nplusone.ext.pytest_plugin import _ReportListener, _WarnListener

_NPLUSONE_CLONE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestReportListener(unittest.TestCase):
    def test_notify_adds_to_report(self):
        from nplusone.core.listeners import LazyLoadMessage

        class FakeModel(object):
            pass

        report = Report()
        listener = _ReportListener(report)
        msg = LazyLoadMessage(FakeModel, "bar")
        listener.notify(msg)
        assert len(report) == 1
        assert report.entries[0].model == "FakeModel"
        assert report.entries[0].field == "bar"

    def test_notify_respects_current_test(self):
        from nplusone.core.listeners import LazyLoadMessage

        class FakeModel(object):
            pass

        report = Report()
        report.set_current_test("tests/test_x.py::test_y")
        listener = _ReportListener(report)
        listener.notify(LazyLoadMessage(FakeModel, "bar"))
        assert report.entries[0].test_name == "tests/test_x.py::test_y"

    def test_warn_listener_logs(self):
        from nplusone.core.listeners import LazyLoadMessage

        class FakeModel(object):
            __name__ = "FakeModel"

        listener = _WarnListener()
        with mock.patch.object(listener.logger, "warning") as mock_warning:
            listener.notify(LazyLoadMessage(FakeModel, "items"))
        mock_warning.assert_called_once()
        args, _kwargs = mock_warning.call_args
        assert any("Potential n+1" in str(a) for a in args)


def _run_pytest_subprocess(tmp_dir, test_code, extra_args=None):
    test_file = os.path.join(tmp_dir, "test_sample.py")
    with open(test_file, "w") as f:
        f.write(textwrap.dedent(test_code))
    args = [
        sys.executable,
        "-m",
        "pytest",
        test_file,
        "-p",
        "no:cacheprovider",
        "--override-ini=addopts=",
        "--no-header",
    ]
    if extra_args:
        args.extend(extra_args)
    py_path = _NPLUSONE_CLONE_ROOT
    prev_pp = os.environ.get("PYTHONPATH", "")
    if prev_pp:
        py_path = py_path + os.pathsep + prev_pp
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=tmp_dir,
        env=dict(os.environ, DJANGO_SETTINGS_MODULE="", PYTHONPATH=py_path),
    )
    return result


class TestPytestPluginIntegration(unittest.TestCase):
    def test_report_text_output(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Widget(object):
                    pass

                def test_trigger():
                    # First send a load event to register the instance
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Widget:1'],
                    )
                    # Then send a lazy_load for that instance
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Widget, 'Widget:1', 'parts'),
                    )
            """,
                extra_args=["--nplusone-report"],
            )
            assert "nplusone Report" in result.stdout
            assert "Widget" in result.stdout
            assert "parts" in result.stdout
            assert "n_plus_one" in result.stdout

    def test_report_json_to_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            outfile = os.path.join(tmp_dir, "report.json")
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Gadget(object):
                    pass

                def test_trigger():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Gadget:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Gadget, 'Gadget:1', 'widgets'),
                    )
            """,
                extra_args=[
                    "--nplusone-report",
                    "--nplusone-report-file={0}".format(outfile),
                ],
            )
            assert "nplusone report written to" in result.stdout
            matches = glob.glob(os.path.join(tmp_dir, "report-*.json"))
            assert len(matches) == 1
            with open(matches[0]) as f:
                data = json.load(f)
            assert data["total_issues"] >= 1
            group = data["groups"][0]
            assert group["model"] == "Gadget"
            assert group["field"] == "widgets"
            assert group["error_type"] == "n_plus_one"
            assert len(group["tests"]) >= 1
            assert any("test_trigger" in t for t in group["tests"])

    def test_report_text_to_file_auto_format_from_txt_extension(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            outfile = os.path.join(tmp_dir, "report.txt")
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Widget(object):
                    pass

                def test_trigger():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Widget:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Widget, 'Widget:1', 'parts'),
                    )
            """,
                extra_args=[
                    "--nplusone-report",
                    "--nplusone-report-file={0}".format(outfile),
                ],
            )
            assert "nplusone report written to" in result.stdout
            matches = glob.glob(os.path.join(tmp_dir, "report-*.txt"))
            assert len(matches) == 1
            with open(matches[0]) as f:
                body = f.read()
            assert "nplusone Report" in body
            assert "Widget" in body

    def test_report_json_file_suffix_template(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            pattern = os.path.join(tmp_dir, "nplusone-{suffix}.json")
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Gadget(object):
                    pass

                def test_trigger():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Gadget:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Gadget, 'Gadget:1', 'widgets'),
                    )
            """,
                extra_args=[
                    "--nplusone-report",
                    "--nplusone-report-file={0}".format(pattern),
                ],
            )
            assert result.returncode == 0
            matches = glob.glob(os.path.join(tmp_dir, "nplusone-*.json"))
            assert len(matches) == 1
            assert "{suffix}" not in matches[0]
            with open(matches[0]) as f:
                data = json.load(f)
            assert data["total_issues"] >= 1

    def test_report_file_auto_suffix_two_runs_no_clobber(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            base = os.path.join(tmp_dir, "out.json")
            snippet = """
                from nplusone.core import signals

                class G(object):
                    pass

                def test_t():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['G:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (G, 'G:1', 'x'),
                    )
            """
            r1 = _run_pytest_subprocess(
                tmp_dir,
                snippet,
                extra_args=[
                    "--nplusone-report",
                    "--nplusone-report-file={0}".format(base),
                ],
            )
            r2 = _run_pytest_subprocess(
                tmp_dir,
                snippet,
                extra_args=[
                    "--nplusone-report",
                    "--nplusone-report-file={0}".format(base),
                ],
            )
            assert r1.returncode == 0
            assert r2.returncode == 0
            matches = glob.glob(os.path.join(tmp_dir, "out-*.json"))
            assert len(matches) == 2

    def test_no_flag_no_report(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                def test_nothing():
                    pass
            """,
            )
            assert "nplusone Report" not in result.stdout

    def test_report_includes_test_names(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Order(object):
                    pass

                def test_first():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Order:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Order, 'Order:1', 'items'),
                    )

                def test_second():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Order:2'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Order, 'Order:2', 'items'),
                    )
            """,
                extra_args=["--nplusone-report"],
            )
            assert "Tests:" in result.stdout
            assert "test_first" in result.stdout
            assert "test_second" in result.stdout

    def test_empty_report(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                def test_clean():
                    pass
            """,
                extra_args=["--nplusone-report"],
            )
            assert "No n+1 issues detected" in result.stdout

    def test_nplusone_error_raises(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class StrictModel(object):
                    pass

                def test_triggers_nplusone():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['StrictModel:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (StrictModel, 'StrictModel:1', 'items'),
                    )
            """,
                extra_args=["--nplusone-error"],
            )
            assert result.returncode != 0
            out = result.stdout + result.stderr
            assert "NPlusOneError" in out or "Potential n+1" in out

    def test_nplusone_warn_only_passes(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class WarnModel(object):
                    pass

                def test_triggers_nplusone():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['WarnModel:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (WarnModel, 'WarnModel:1', 'items'),
                    )
            """,
                extra_args=[
                    "--nplusone",
                    "-o",
                    "log_cli=true",
                    "-o",
                    "log_cli_level=WARNING",
                    "-o",
                    "log_cli_format=%(message)s",
                ],
            )
            assert result.returncode == 0
            out = result.stdout + result.stderr
            assert "Potential n+1" in out

    def test_nplusone_with_error_raises(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class StrictModel(object):
                    pass

                def test_triggers_nplusone():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['StrictModel:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (StrictModel, 'StrictModel:1', 'items'),
                    )
            """,
                extra_args=["--nplusone", "--nplusone-error"],
            )
            assert result.returncode != 0
            out = result.stdout + result.stderr
            assert "NPlusOneError" in out or "Potential n+1" in out

    def test_nplusone_with_report_combined_flags(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Widget(object):
                    pass

                def test_trigger():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Widget:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Widget, 'Widget:1', 'parts'),
                    )
            """,
                extra_args=["--nplusone", "--nplusone-report"],
            )
            assert "nplusone Report" in result.stdout
            assert "Widget" in result.stdout
            assert "parts" in result.stdout

    def test_nplusone_report_and_error_fails_test(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Widget(object):
                    pass

                def test_trigger():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Widget:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Widget, 'Widget:1', 'parts'),
                    )
            """,
                extra_args=["--nplusone-report", "--nplusone-error"],
            )
            assert result.returncode != 0
            out = result.stdout + result.stderr
            assert "Potential n+1" in out or "NPlusOneError" in out
            assert "Widget" in out

    def test_nplusone_report_django_all_flags(self):
        try:
            import django  # noqa: F401
        except ImportError:
            self.skipTest("django not installed")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                from nplusone.core import signals

                class Gadget(object):
                    pass

                def test_trigger():
                    signals.load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c, r: ['Gadget:1'],
                    )
                    signals.lazy_load.send(
                        signals.get_worker(),
                        args=None, kwargs=None, context=None, ret=None,
                        parser=lambda a, k, c: (Gadget, 'Gadget:1', 'widgets'),
                    )
            """,
                extra_args=[
                    "--nplusone",
                    "--nplusone-report",
                    "--nplusone-django",
                ],
            )
            assert result.returncode == 0
            assert "nplusone Report" in result.stdout
            assert "Gadget" in result.stdout

    def test_nplusone_django_only_no_listeners(self):
        try:
            import django  # noqa: F401
        except ImportError:
            self.skipTest("django not installed")
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(
                tmp_dir,
                """
                def test_clean():
                    pass
            """,
                extra_args=["--nplusone-django"],
            )
            assert result.returncode == 0
            assert "nplusone Report" not in result.stdout
