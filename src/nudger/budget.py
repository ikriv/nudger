"""Persistent API spending limits shared by live experiment runs."""
import json
from dataclasses import dataclass
from pathlib import Path
import threading
import uuid


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class Reservation:
    identifier: str
    estimated_cost_usd: float


class Budget:
    def __init__(self, directory, limit):
        self.directory = Path(directory)
        self.limit = limit
        self.journal = self.directory / "usage.jsonl"
        self.lock = self.directory / ".budget.lock"
        self.is_budget_lock_acquired = False
        self._journal_lock = threading.RLock()

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            with self.lock.open("x", encoding="utf-8") as stream:
                stream.write("One live process owns this output directory.\n")
        except FileExistsError:
            raise BudgetExceeded("Output directory is locked by another run. See docs/running.md.") from None
        self.is_budget_lock_acquired = True
        return self

    def __exit__(self, *exc):
        if self.is_budget_lock_acquired:
            self.lock.unlink()

    def append(self, row):
        with self._journal_lock:
            with self.journal.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row) + "\n")

    def charged(self):
        with self._journal_lock:
            latest = {}
            if self.journal.exists():
                for line in self.journal.read_text(encoding="utf-8").splitlines():
                    row = json.loads(line)
                    latest[row["id"]] = row["usd"]
            return sum(latest.values())

    def reserve(self, payload, max_output, prices):
        with self._journal_lock:
            if not self.is_budget_lock_acquired:
                raise BudgetExceeded("Acquire the budget lock before making a request.")
            # Generous text-token allowance plus provider framing, not a billing
            # guarantee. No discounts assumed. Unknown outcomes retain this charge.
            allowance = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 8192
            usd = (allowance * prices[0] + max_output * prices[1]) / 1_000_000
            if self.charged() + usd > self.limit:
                raise BudgetExceeded("The next request would exceed the configured cost allowance.")
            identifier = uuid.uuid4().hex
            self.append({"id": identifier, "event": "reserved", "usd": usd})
            return Reservation(identifier, usd)

    def settle(self, reservation, usd, input_tokens, output_tokens):
        self.append({"id": reservation.identifier, "event": "settled", "usd": usd,
                     "input_tokens": input_tokens, "output_tokens": output_tokens})
