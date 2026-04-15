# -*- coding: utf-8 -*-

import json
from collections import defaultdict

from nplusone.core import stack


def merge_report_dicts(dicts):
    if not dicts:
        return {"total_issues": 0, "groups": []}
    merged_groups = {}
    total_issues = 0
    for d in dicts:
        total_issues += d.get("total_issues", 0)
        for g in d.get("groups", []):
            key = (g["model"], g["field"], g["error_type"], g["caller"])
            if key not in merged_groups:
                merged_groups[key] = {
                    "model": g["model"],
                    "field": g["field"],
                    "error_type": g["error_type"],
                    "caller": g["caller"],
                    "count": g["count"],
                    "message": g["message"],
                    "locations": sorted(set(g.get("locations") or [])),
                    "tests": sorted(set(g.get("tests") or [])),
                }
            else:
                m = merged_groups[key]
                m["count"] += g["count"]
                m["locations"] = sorted(set(m["locations"]) | set(g.get("locations") or []))
                m["tests"] = sorted(set(m["tests"]) | set(g.get("tests") or []))
    groups = sorted(
        merged_groups.values(),
        key=lambda x: (x["model"], x["field"], x["error_type"], x["caller"]),
    )
    return {"total_issues": total_issues, "groups": groups}


def report_dict_to_text(data):
    aggregated = data.get("groups") or []
    if not aggregated:
        return "No n+1 issues detected."
    lines = []
    lines.append("nplusone Report")
    lines.append("=" * 60)
    lines.append("Total issues: {0}".format(data.get("total_issues", 0)))
    lines.append("Unique groups: {0}".format(len(aggregated)))
    lines.append("")
    for i, group in enumerate(aggregated, 1):
        lines.append("{0}. {1}".format(i, group["message"]))
        lines.append("   Model:      {0}".format(group["model"]))
        lines.append("   Field:      {0}".format(group["field"]))
        lines.append("   Error type: {0}".format(group["error_type"]))
        lines.append("   Caller:     {0}".format(group["caller"]))
        lines.append("   Count:      {0}".format(group["count"]))
        if group["locations"]:
            lines.append("   Locations:")
            for loc in group["locations"]:
                lines.append("     - {0}".format(loc))
        if group["tests"]:
            lines.append("   Tests:")
            for test in group["tests"]:
                lines.append("     - {0}".format(test))
        lines.append("")
    return "\n".join(lines)


class ReportEntry(object):
    def __init__(self, message, caller=None, test_name=None):
        self.model = message.model.__name__
        self.field = message.field
        self.label = message.label
        self.message = message.message
        self.caller = self._parse_caller(caller)
        self.test_name = test_name

    @staticmethod
    def _parse_caller(caller):
        if caller is None:
            return None
        return {
            "filename": caller[1],
            "lineno": caller[2],
            "function": caller[3],
        }

    @property
    def group_key(self):
        caller_func = self.caller["function"] if self.caller else "unknown"
        return (self.model, self.field, self.label, caller_func)


class Report(object):
    def __init__(self):
        self.entries = []
        self._current_test = None

    def set_current_test(self, test_name):
        self._current_test = test_name

    def clear_current_test(self):
        self._current_test = None

    def add(self, message, caller=None):
        self.entries.append(ReportEntry(message, caller, test_name=self._current_test))

    @property
    def aggregated(self):
        groups = defaultdict(list)
        for entry in self.entries:
            groups[entry.group_key].append(entry)
        result = []
        for (model, field, label, caller_func), entries in sorted(groups.items()):
            callers = []
            tests = []
            for entry in entries:
                if entry.caller:
                    callers.append("{filename}:{lineno}".format(**entry.caller))
                if entry.test_name:
                    tests.append(entry.test_name)
            result.append(
                {
                    "model": model,
                    "field": field,
                    "error_type": label,
                    "caller": caller_func,
                    "count": len(entries),
                    "message": entries[0].message,
                    "locations": sorted(set(callers)),
                    "tests": sorted(set(tests)),
                }
            )
        return result

    def to_text(self):
        return report_dict_to_text(self.to_dict())

    def to_dict(self):
        return {
            "total_issues": len(self.entries),
            "groups": self.aggregated,
        }

    def to_json(self, **kwargs):
        return json.dumps(self.to_dict(), **kwargs)

    def __len__(self):
        return len(self.entries)

    def __bool__(self):
        return bool(self.entries)

    __nonzero__ = __bool__
