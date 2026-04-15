# -*- coding: utf-8 -*-

import six

from nplusone.core import listeners
from nplusone.core import exceptions
from nplusone.core import stack
from nplusone.core.report import Report


class Profiler(object):

    CALLER_PATTERNS = [
        'site-packages', 'nplusone/core', 'nplusone/ext',
    ]

    def __init__(self, whitelist=None, report=None):
        self.whitelist = [
            listeners.Rule(**item)
            for item in (whitelist or [])
        ]
        self.report = report

    def __enter__(self):
        self.listeners = {}
        for name, listener_type in six.iteritems(listeners.listeners):
            self.listeners[name] = listener_type(self)
            self.listeners[name].setup()
        return self

    def __exit__(self, *exc):
        for name in six.iterkeys(listeners.listeners):
            self.listeners.pop(name).teardown()

    def notify(self, message):
        if not message.match(self.whitelist):
            if self.report is not None:
                caller = stack.get_caller(patterns=self.CALLER_PATTERNS)
                self.report.add(message, caller)
            else:
                raise exceptions.NPlusOneError(message.message)
