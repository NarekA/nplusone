# -*- coding: utf-8 -*-

import os

import pytest

from nplusone.core.report import Report
from nplusone.core import listeners
from nplusone.core import stack


_report = Report()


class _ReportListener(object):

    CALLER_PATTERNS = [
        'site-packages', 'nplusone/core', 'nplusone/ext',
    ]

    def __init__(self, report):
        self.report = report

    def notify(self, message):
        caller = stack.get_caller(patterns=self.CALLER_PATTERNS)
        self.report.add(message, caller)


def pytest_addoption(parser):
    group = parser.getgroup('nplusone')
    group.addoption(
        '--nplusone-report',
        action='store_true',
        default=False,
        dest='nplusone_report',
        help='Generate an nplusone report of n+1 query issues detected during tests.',
    )
    group.addoption(
        '--nplusone-report-file',
        action='store',
        default=None,
        dest='nplusone_report_file',
        help='Write the nplusone report to a file (default: print to terminal).',
    )
    group.addoption(
        '--nplusone-report-format',
        action='store',
        default='text',
        dest='nplusone_report_format',
        choices=['text', 'json'],
        help='Report output format: text or json (default: text).',
    )


def pytest_configure(config):
    if not config.getoption('nplusone_report', default=False):
        return
    global _report
    _report = Report()
    config._nplusone_report = _report
    config._nplusone_listener_parent = _ReportListener(_report)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    report = getattr(item.config, '_nplusone_report', None)
    if report is None:
        yield
        return

    parent = item.config._nplusone_listener_parent
    report.set_current_test(item.nodeid)
    active_listeners = {}
    for name, listener_type in listeners.listeners.items():
        active_listeners[name] = listener_type(parent)
        active_listeners[name].setup()
    try:
        yield
    finally:
        for name in list(active_listeners):
            active_listeners.pop(name).teardown()
        report.clear_current_test()


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    report = getattr(config, '_nplusone_report', None)
    if report is None:
        return

    fmt = config.getoption('nplusone_report_format', default='text')
    outfile = config.getoption('nplusone_report_file', default=None)

    if fmt == 'json':
        content = report.to_json(indent=2)
    else:
        content = report.to_text()

    if outfile:
        with open(outfile, 'w') as f:
            f.write(content)
            f.write('\n')
        terminalreporter.write_line(
            'nplusone report written to: {0}'.format(outfile)
        )
    else:
        terminalreporter.write_line('')
        terminalreporter.write_line(content)
