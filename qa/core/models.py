from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Status(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


@dataclass
class TestResult:
    name: str
    status: Status
    duration_ms: float
    detail: str | None = None
    expected: Any = None
    got: Any = None


@dataclass
class SuiteResult:
    name: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == Status.PASS)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if r.status != Status.PASS)

    @property
    def total(self) -> int:
        return len(self.results)


@dataclass
class RunReport:
    timestamp: str
    suites: list[SuiteResult] = field(default_factory=list)

    @property
    def total_passed(self) -> int:
        return sum(s.passed for s in self.suites)

    @property
    def total_failed(self) -> int:
        return sum(s.failed for s in self.suites)

    @property
    def total_tests(self) -> int:
        return sum(s.total for s in self.suites)
