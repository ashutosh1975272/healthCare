from datetime import date

import pytest
from pydantic import ValidationError

from app.services.xomni_service import _is_action_confirmation, _is_action_rejection
from app.schemas.time import TodoIn


def test_timed_todo_schema_accepts_recurrence() -> None:
    todo = TodoIn(
        title="Walk",
        due_date=date(2026, 9, 9),
        start_minute=840,
        end_minute=960,
        recurrence_rule="weekdays",
        recurrence_until=date(2026, 9, 30),
    )
    assert todo.start_minute == 840
    assert todo.recurrence_rule == "weekdays"


def test_timed_todo_schema_rejects_out_of_range_minutes() -> None:
    with pytest.raises(ValidationError):
        TodoIn(title="Broken", due_date=date(2026, 9, 9), start_minute=900, end_minute=1441)


def test_xomni_confirmation_phrases_are_channel_neutral() -> None:
    assert _is_action_confirmation("Yes, update it")
    assert _is_action_confirmation("confirm")
    assert _is_action_confirmation("go ahead")
    assert _is_action_rejection("No, leave it unchanged")
    assert not _is_action_confirmation("maybe change the time")
