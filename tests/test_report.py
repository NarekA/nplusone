# -*- coding: utf-8 -*-

import json
import unittest

from nplusone.core.listeners import LazyLoadMessage, EagerLoadMessage
from nplusone.core.report import Report, ReportEntry
from nplusone.core.notifiers import ReportNotifier
from nplusone.core.profiler import Profiler


class FakeModel(object):
    __name__ = 'FakeModel'


class OtherModel(object):
    __name__ = 'OtherModel'


class TestReportEntry(unittest.TestCase):

    def test_group_key(self):
        msg = LazyLoadMessage(FakeModel, 'items')
        caller = ('/app/views.py', '/app/views.py', 42, 'get_items', None, None)
        entry = ReportEntry(msg, caller)
        assert entry.group_key == ('FakeModel', 'items', 'n_plus_one', 'get_items')

    def test_group_key_no_caller(self):
        msg = LazyLoadMessage(FakeModel, 'items')
        entry = ReportEntry(msg, caller=None)
        assert entry.group_key == ('FakeModel', 'items', 'n_plus_one', 'unknown')

    def test_parse_caller(self):
        caller = ('/app/views.py', '/app/views.py', 42, 'get_items', None, None)
        entry = ReportEntry(LazyLoadMessage(FakeModel, 'items'), caller)
        assert entry.caller == {
            'filename': '/app/views.py',
            'lineno': 42,
            'function': 'get_items',
        }

    def test_parse_caller_none(self):
        entry = ReportEntry(LazyLoadMessage(FakeModel, 'items'), None)
        assert entry.caller is None

    def test_stores_message_fields(self):
        msg = EagerLoadMessage(FakeModel, 'related')
        entry = ReportEntry(msg)
        assert entry.model == 'FakeModel'
        assert entry.field == 'related'
        assert entry.label == 'unused_eager_load'
        assert 'FakeModel.related' in entry.message

    def test_stores_test_name(self):
        msg = LazyLoadMessage(FakeModel, 'items')
        entry = ReportEntry(msg, test_name='test_foo::test_bar')
        assert entry.test_name == 'test_foo::test_bar'

    def test_test_name_defaults_none(self):
        msg = LazyLoadMessage(FakeModel, 'items')
        entry = ReportEntry(msg)
        assert entry.test_name is None


class TestReport(unittest.TestCase):

    def test_empty_report(self):
        report = Report()
        assert len(report) == 0
        assert not report
        assert report.aggregated == []
        assert report.to_text() == 'No n+1 issues detected.'

    def test_add_entries(self):
        report = Report()
        msg1 = LazyLoadMessage(FakeModel, 'items')
        msg2 = LazyLoadMessage(FakeModel, 'items')
        report.add(msg1)
        report.add(msg2)
        assert len(report) == 2
        assert report

    def test_aggregation_groups_by_key(self):
        report = Report()
        caller1 = (None, '/app/views.py', 10, 'list_view', None, None)
        caller2 = (None, '/app/views.py', 10, 'list_view', None, None)
        caller3 = (None, '/app/views.py', 20, 'detail_view', None, None)

        report.add(LazyLoadMessage(FakeModel, 'items'), caller1)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller2)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller3)

        agg = report.aggregated
        assert len(agg) == 2

        list_group = next(g for g in agg if g['caller'] == 'list_view')
        assert list_group['count'] == 2
        assert list_group['model'] == 'FakeModel'
        assert list_group['field'] == 'items'
        assert list_group['error_type'] == 'n_plus_one'

        detail_group = next(g for g in agg if g['caller'] == 'detail_view')
        assert detail_group['count'] == 1

    def test_aggregation_different_error_types(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.add(EagerLoadMessage(FakeModel, 'items'), caller)
        agg = report.aggregated
        assert len(agg) == 2

    def test_aggregation_different_models(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.add(LazyLoadMessage(OtherModel, 'items'), caller)
        agg = report.aggregated
        assert len(agg) == 2

    def test_aggregation_different_fields(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.add(LazyLoadMessage(FakeModel, 'widgets'), caller)
        agg = report.aggregated
        assert len(agg) == 2

    def test_aggregation_locations_deduped(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        agg = report.aggregated
        assert len(agg[0]['locations']) == 1
        assert agg[0]['locations'] == ['/app/views.py:10']

    def test_aggregation_includes_tests(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.set_current_test('tests/test_foo.py::test_bar')
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.set_current_test('tests/test_foo.py::test_baz')
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.clear_current_test()
        agg = report.aggregated
        assert len(agg) == 1
        assert agg[0]['tests'] == [
            'tests/test_foo.py::test_bar',
            'tests/test_foo.py::test_baz',
        ]

    def test_aggregation_dedupes_tests(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.set_current_test('tests/test_foo.py::test_bar')
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        agg = report.aggregated
        assert agg[0]['tests'] == ['tests/test_foo.py::test_bar']

    def test_aggregation_no_test_name(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        agg = report.aggregated
        assert agg[0]['tests'] == []

    def test_to_text_empty(self):
        report = Report()
        assert report.to_text() == 'No n+1 issues detected.'

    def test_to_text_with_entries(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        text = report.to_text()
        assert 'nplusone Report' in text
        assert 'Total issues: 1' in text
        assert 'FakeModel' in text
        assert 'items' in text
        assert 'n_plus_one' in text
        assert 'list_view' in text
        assert '/app/views.py:10' in text

    def test_to_text_with_tests(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.set_current_test('tests/test_foo.py::test_bar')
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        report.clear_current_test()
        text = report.to_text()
        assert 'Tests:' in text
        assert 'tests/test_foo.py::test_bar' in text

    def test_to_dict(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        d = report.to_dict()
        assert d['total_issues'] == 1
        assert len(d['groups']) == 1
        group = d['groups'][0]
        assert group['model'] == 'FakeModel'
        assert group['field'] == 'items'
        assert group['error_type'] == 'n_plus_one'
        assert group['caller'] == 'list_view'
        assert group['count'] == 1
        assert group['tests'] == []

    def test_to_json(self):
        report = Report()
        caller = (None, '/app/views.py', 10, 'list_view', None, None)
        report.add(LazyLoadMessage(FakeModel, 'items'), caller)
        j = report.to_json()
        data = json.loads(j)
        assert data['total_issues'] == 1
        assert data['groups'][0]['model'] == 'FakeModel'

    def test_bool_empty(self):
        report = Report()
        assert not report

    def test_bool_non_empty(self):
        report = Report()
        report.add(LazyLoadMessage(FakeModel, 'items'))
        assert report

    def test_set_and_clear_current_test(self):
        report = Report()
        assert report._current_test is None
        report.set_current_test('test_foo')
        assert report._current_test == 'test_foo'
        report.add(LazyLoadMessage(FakeModel, 'items'))
        assert report.entries[0].test_name == 'test_foo'
        report.clear_current_test()
        assert report._current_test is None
        report.add(LazyLoadMessage(FakeModel, 'items'))
        assert report.entries[1].test_name is None


class TestReportNotifier(unittest.TestCase):

    def test_is_enabled_default(self):
        assert not ReportNotifier.is_enabled({})

    def test_is_enabled_when_configured(self):
        assert ReportNotifier.is_enabled({'NPLUSONE_REPORT': True})

    def test_notify_adds_to_report(self):
        report = Report()
        notifier = ReportNotifier({'NPLUSONE_REPORT_OBJECT': report})
        msg = LazyLoadMessage(FakeModel, 'items')
        notifier.notify(msg)
        assert len(report) == 1
        assert report.entries[0].model == 'FakeModel'
        assert report.entries[0].field == 'items'

    def test_uses_provided_report(self):
        report = Report()
        notifier = ReportNotifier({'NPLUSONE_REPORT_OBJECT': report})
        assert notifier.report is report

    def test_creates_default_report(self):
        notifier = ReportNotifier({})
        assert isinstance(notifier.report, Report)


class TestProfilerReport(unittest.TestCase):

    def test_profiler_collects_to_report(self):
        report = Report()
        profiler = Profiler(report=report)
        msg = LazyLoadMessage(FakeModel, 'items')
        profiler.notify(msg)
        assert len(report) == 1

    def test_profiler_without_report_raises(self):
        profiler = Profiler()
        msg = LazyLoadMessage(FakeModel, 'items')
        from nplusone.core.exceptions import NPlusOneError
        with self.assertRaises(NPlusOneError):
            profiler.notify(msg)

    def test_profiler_enter_returns_self(self):
        profiler = Profiler()
        result = profiler.__enter__()
        assert result is profiler
        profiler.__exit__(None, None, None)

    def test_profiler_context_manager_with_report(self):
        report = Report()
        with Profiler(report=report) as p:
            assert p.report is report

    def test_profiler_report_respects_whitelist(self):
        report = Report()
        profiler = Profiler(
            whitelist=[{'model': 'FakeModel', 'field': 'items'}],
            report=report,
        )
        msg = LazyLoadMessage(FakeModel, 'items')
        profiler.notify(msg)
        assert len(report) == 0
