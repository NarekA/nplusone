# -*- coding: utf-8 -*-

import json
import os
import subprocess
import sys
import textwrap
import unittest

from nplusone.core.report import Report
from nplusone.ext.pytest_plugin import _ReportListener


class TestReportListener(unittest.TestCase):

    def test_notify_adds_to_report(self):
        from nplusone.core.listeners import LazyLoadMessage

        class FakeModel(object):
            pass

        report = Report()
        listener = _ReportListener(report)
        msg = LazyLoadMessage(FakeModel, 'bar')
        listener.notify(msg)
        assert len(report) == 1
        assert report.entries[0].model == 'FakeModel'
        assert report.entries[0].field == 'bar'

    def test_notify_respects_current_test(self):
        from nplusone.core.listeners import LazyLoadMessage

        class FakeModel(object):
            pass

        report = Report()
        report.set_current_test('tests/test_x.py::test_y')
        listener = _ReportListener(report)
        listener.notify(LazyLoadMessage(FakeModel, 'bar'))
        assert report.entries[0].test_name == 'tests/test_x.py::test_y'


def _run_pytest_subprocess(tmp_dir, test_code, extra_args=None):
    test_file = os.path.join(tmp_dir, 'test_sample.py')
    with open(test_file, 'w') as f:
        f.write(textwrap.dedent(test_code))
    args = [
        sys.executable, '-m', 'pytest', test_file,
        '-p', 'no:cacheprovider',
        '--override-ini=addopts=',
        '--no-header',
    ]
    if extra_args:
        args.extend(extra_args)
    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        cwd=tmp_dir,
        env=dict(os.environ, DJANGO_SETTINGS_MODULE=''),
    )
    return result


class TestPytestPluginIntegration(unittest.TestCase):

    def test_report_text_output(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(tmp_dir, """
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
            """, extra_args=['--nplusone-report'])
            assert 'nplusone Report' in result.stdout
            assert 'Widget' in result.stdout
            assert 'parts' in result.stdout
            assert 'n_plus_one' in result.stdout

    def test_report_json_to_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            outfile = os.path.join(tmp_dir, 'report.json')
            result = _run_pytest_subprocess(tmp_dir, """
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
            """, extra_args=[
                '--nplusone-report',
                '--nplusone-report-format=json',
                '--nplusone-report-file={0}'.format(outfile),
            ])
            assert 'nplusone report written to' in result.stdout
            with open(outfile) as f:
                data = json.load(f)
            assert data['total_issues'] >= 1
            group = data['groups'][0]
            assert group['model'] == 'Gadget'
            assert group['field'] == 'widgets'
            assert group['error_type'] == 'n_plus_one'
            assert len(group['tests']) >= 1
            assert any('test_trigger' in t for t in group['tests'])

    def test_no_flag_no_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(tmp_dir, """
                def test_nothing():
                    pass
            """)
            assert 'nplusone Report' not in result.stdout

    def test_report_includes_test_names(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(tmp_dir, """
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
            """, extra_args=['--nplusone-report'])
            assert 'Tests:' in result.stdout
            assert 'test_first' in result.stdout
            assert 'test_second' in result.stdout

    def test_empty_report(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _run_pytest_subprocess(tmp_dir, """
                def test_clean():
                    pass
            """, extra_args=['--nplusone-report'])
            assert 'No n+1 issues detected' in result.stdout
