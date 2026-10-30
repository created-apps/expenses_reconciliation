"""Rules about which step a reconciliation has reached, enforced on the server (not just by the UI)."""

from typing import Any


class ServiceError(Exception):
    """A request the service refuses; the API turns it into an HTTP error with the same status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


# Statuses from "the statement is confirmed" onwards (project_context / architecture: cycle status flow).
CONFIRMED_OR_LATER = ("statement_confirmed", "invoices_extracted", "matched", "exported")


def require_confirmed_statement(cycle: dict[str, Any]) -> None:
    """Reading invoices and running matching both need a confirmed statement (409 otherwise).
    An exported reconciliation can still be edited (flow.md sections 2 and 8): see `note_edit`."""
    if cycle["status"] not in CONFIRMED_OR_LATER:
        raise ServiceError(409, "Confirm the statement first")


def note_edit(repo, cycle: dict[str, Any], actor: str) -> None:
    """The first edit after an export moves the reconciliation back to `matched`: the Excel that was
    downloaded no longer shows what is in the app, and the screens say so until it is exported again."""
    if cycle["status"] != "exported":
        return
    repo.update_cycle(cycle["id"], {"status": "matched"})
    repo.add_event(cycle["id"], actor, "edited_after_export", {})
    cycle["status"] = "matched"  # the caller's copy follows
