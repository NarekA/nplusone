# -*- coding: utf-8 -*-

import logging

from nplusone.core import exceptions
from nplusone.core import stack
from nplusone.core.report import Report


class Notifier(object):

    CONFIG_KEY = None
    ENABLED_DEFAULT = False

    @classmethod
    def is_enabled(cls, config):
        return (
            config.get(cls.CONFIG_KEY) or
            (
                cls.CONFIG_KEY not in config and
                cls.ENABLED_DEFAULT
            )
        )

    def __init__(self, config):
        self.config = config  # pragma: no cover

    def notify(self, model, field):
        pass  # pragma: no cover


class LogNotifier(Notifier):

    CONFIG_KEY = 'NPLUSONE_LOG'
    ENABLED_DEFAULT = True

    def __init__(self, config):
        self.logger = config.get('NPLUSONE_LOGGER', logging.getLogger('nplusone'))
        self.level = config.get('NPLUSONE_LOG_LEVEL', logging.DEBUG)

    def notify(self, message):
        self.logger.log(self.level, message.message)


class ErrorNotifier(Notifier):

    CONFIG_KEY = 'NPLUSONE_RAISE'
    ENABLED_DEFAULT = False

    def __init__(self, config):
        self.error = config.get('NPLUSONE_ERROR', exceptions.NPlusOneError)

    def notify(self, message):
        raise self.error(message.message)


class ReportNotifier(Notifier):

    CONFIG_KEY = 'NPLUSONE_REPORT'
    ENABLED_DEFAULT = False

    CALLER_PATTERNS = [
        'site-packages', 'nplusone/core', 'nplusone/ext',
    ]

    def __init__(self, config):
        self.report = config.get('NPLUSONE_REPORT_OBJECT', Report())
        self.caller_patterns = config.get(
            'NPLUSONE_REPORT_CALLER_PATTERNS', self.CALLER_PATTERNS
        )

    def notify(self, message):
        caller = stack.get_caller(patterns=self.caller_patterns)
        self.report.add(message, caller)


def init(config):
    return [
        notifier(config) for notifier in (LogNotifier, ErrorNotifier, ReportNotifier)
        if notifier.is_enabled(config)
    ]
