# -*- coding: utf-8 -*-

import json
import logging

import pytest

from nplusone.core import exceptions, listeners, stack
from nplusone.core.report import Report, merge_report_dicts, report_dict_to_text


_report = Report()

_django_nplusone_loaded = False


def _is_xdist_worker(config):
    return getattr(config, "workerinput", None) is not None


def _infer_report_format(config):
    outfile = config.getoption("nplusone_report_file", default=None)
    if outfile and str(outfile).lower().endswith(".json"):
        return "json"
    return "text"


def _ensure_nplusone_django():
    global _django_nplusone_loaded
    if _django_nplusone_loaded:
        return
    try:
        from django.conf import settings
    except ImportError:
        return
    if not settings.configured:
        return
    try:
        import nplusone.ext.django  # noqa: F401
    except ImportError:
        return
    _django_nplusone_loaded = True


class _ReportListener(object):
    CALLER_PATTERNS = [
        "site-packages",
        "nplusone/core",
        "nplusone/ext",
    ]

    def __init__(self, report):
        self.report = report

    def notify(self, message):
        caller = stack.get_caller(patterns=self.CALLER_PATTERNS)
        self.report.add(message, caller)


class _WarnListener(object):
    def __init__(self):
        self.logger = logging.getLogger("nplusone")

    def notify(self, message):
        self.logger.warning("%s", message.message)


class _StrictListener(object):
    def notify(self, message):
        raise exceptions.NPlusOneError(message.message)


class _ReportAndStrictListener(object):
    def __init__(self, report):
        self._report = _ReportListener(report)
        self._strict = _StrictListener()

    def notify(self, message):
        self._report.notify(message)
        self._strict.notify(message)


def _listeners_enabled(config):
    return (
        config.getoption("nplusone", default=False)
        or config.getoption("nplusone_report", default=False)
        or config.getoption("nplusone_error", default=False)
    )


class _NplusoneXdistMergePlugin:
    def pytest_testnodedown(self, node, error):
        if error is not None:
            return
        cfg = getattr(node, "config", None)
        if cfg is None or not cfg.getoption("nplusone_report", default=False):
            return
        payloads = getattr(cfg, "_nplusone_worker_payloads", None)
        if payloads is None:
            return
        wout = getattr(node, "workeroutput", None)
        if not isinstance(wout, dict) or "nplusone_report_dict" not in wout:
            return
        payloads.append(wout["nplusone_report_dict"])


def _register_xdist_merge_plugin(config):
    if not config.getoption("nplusone_report", default=False):
        return
    if getattr(config, "_nplusone_xdist_merge_registered", False):
        return
    if not config.pluginmanager.hasplugin("xdist"):
        return
    config.pluginmanager.register(_NplusoneXdistMergePlugin(), "_nplusone_xdist_merge")
    config._nplusone_xdist_merge_registered = True


def pytest_addoption(parser):
    group = parser.getgroup("nplusone")
    group.addoption(
        "--nplusone",
        action="store_true",
        default=False,
        dest="nplusone",
        help=(
            "Enable nplusone listeners for each test (lazy/eager detection). "
            "Violations are logged as warnings unless --nplusone-error or "
            "--nplusone-report is used."
        ),
    )
    group.addoption(
        "--nplusone-error",
        action="store_true",
        default=False,
        dest="nplusone_error",
        help=(
            "On nplusone violations, raise NPlusOneError (fail the test). "
            "Can be combined with --nplusone-report (violations are recorded "
            "then the test fails)."
        ),
    )
    group.addoption(
        "--nplusone-django",
        action="store_true",
        default=False,
        dest="nplusone_django",
        help=(
            "Import the Django ORM integration (nplusone.ext.django). "
            "Use with --nplusone and/or --nplusone-report when testing Django."
        ),
    )
    group.addoption(
        "--nplusone-report",
        action="store_true",
        default=False,
        dest="nplusone_report",
        help="Generate an nplusone report of n+1 query issues detected during tests.",
    )
    group.addoption(
        "--nplusone-report-file",
        action="store",
        default=None,
        dest="nplusone_report_file",
        help=(
            "Write the nplusone report to a file (default: print to terminal). "
            "Format is inferred from the path: names ending in .json are JSON; otherwise plain text."
        ),
    )


def pytest_configure(config):
    if config.getoption("nplusone_django", default=False):
        try:
            import nplusone.ext.django  # noqa: F401
        except ImportError as err:
            raise pytest.UsageError("--nplusone-django requires Django to be installed ({0})".format(err))

    if not _listeners_enabled(config):
        return

    if config.getoption("nplusone_report", default=False):
        global _report
        _report = Report()
        config._nplusone_report = _report
        config._nplusone_worker_payloads = []
        _register_xdist_merge_plugin(config)
        if config.getoption("nplusone_error", default=False):
            config._nplusone_listener_parent = _ReportAndStrictListener(_report)
        else:
            config._nplusone_listener_parent = _ReportListener(_report)
    elif config.getoption("nplusone_error", default=False):
        config._nplusone_report = None
        config._nplusone_listener_parent = _StrictListener()
    else:
        config._nplusone_report = None
        config._nplusone_listener_parent = _WarnListener()


def pytest_sessionstart(session):
    _register_xdist_merge_plugin(session.config)


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    parent = getattr(item.config, "_nplusone_listener_parent", None)
    if parent is None:
        yield
        return

    _ensure_nplusone_django()

    report = getattr(item.config, "_nplusone_report", None)
    if report is not None:
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
        if report is not None:
            report.clear_current_test()


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if not config.getoption("nplusone_report", default=False):
        return
    report = getattr(config, "_nplusone_report", None)
    if report is None:
        return
    workeroutput = getattr(config, "workeroutput", None)
    if isinstance(workeroutput, dict):
        workeroutput["nplusone_report_dict"] = report.to_dict()


@pytest.hookimpl(trylast=True)
def pytest_terminal_summary(terminalreporter, exitstatus, config):
    if not config.getoption("nplusone_report", default=False):
        return
    if _is_xdist_worker(config):
        return

    report = getattr(config, "_nplusone_report", None)
    if report is None:
        return

    fmt = _infer_report_format(config)
    outfile = config.getoption("nplusone_report_file", default=None)

    payloads = list(getattr(config, "_nplusone_worker_payloads", None) or [])
    if report.entries:
        payloads.append(report.to_dict())
    if payloads:
        merged = merge_report_dicts(payloads)
        if fmt == "json":
            content = json.dumps(merged, indent=2)
        else:
            content = report_dict_to_text(merged)
    else:
        if fmt == "json":
            content = json.dumps({"total_issues": 0, "groups": []}, indent=2)
        else:
            content = report_dict_to_text({"total_issues": 0, "groups": []})

    if outfile:
        with open(outfile, "w") as f:
            f.write(content)
            f.write("\n")
        terminalreporter.write_line("nplusone report written to: {0}".format(outfile))
    else:
        terminalreporter.write_line("")
        terminalreporter.write_line(content)
