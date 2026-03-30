"""User tag carry-over when stress/recovery window bounds shift on recompute."""

from datetime import datetime

from api.services.tracking_service import _carry_user_tag_from_prior_intervals


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _key(a: str, b: str) -> tuple[datetime, datetime]:
    return (_dt(a), _dt(b))


def test_exact_key_returns_tag():
    k = _key("2024-01-15T10:00:00+00:00", "2024-01-15T10:20:00+00:00")
    exact = {k: ("work_calls", "user_confirmed")}
    prior = [(_dt("2024-01-15T10:00:00+00:00"), _dt("2024-01-15T10:20:00+00:00"), "work_calls", "user_confirmed")]
    t, src = _carry_user_tag_from_prior_intervals(
        started_at=k[0],
        ended_at=k[1],
        exact_key=k,
        exact_map=exact,
        prior_intervals=prior,
    )
    assert t == "work_calls"
    assert src == "user_confirmed"


def test_overlap_when_bounds_shift_slightly():
    """Recomputed window starts/ends a few minutes later — tag still applies."""
    old_s, old_e = _dt("2024-01-15T10:00:00+00:00"), _dt("2024-01-15T10:20:00+00:00")
    new_s, new_e = _dt("2024-01-15T10:02:00+00:00"), _dt("2024-01-15T10:22:00+00:00")
    prior = [(old_s, old_e, "work_calls", "user_confirmed")]
    new_key = _key("2024-01-15T10:02:00+00:00", "2024-01-15T10:22:00+00:00")
    t, _ = _carry_user_tag_from_prior_intervals(
        started_at=new_s,
        ended_at=new_e,
        exact_key=new_key,
        exact_map={},
        prior_intervals=prior,
    )
    assert t == "work_calls"


def test_no_match_when_intervals_disjoint():
    old_s, old_e = _dt("2024-01-15T10:00:00+00:00"), _dt("2024-01-15T10:20:00+00:00")
    new_s, new_e = _dt("2024-01-15T11:00:00+00:00"), _dt("2024-01-15T11:20:00+00:00")
    prior = [(old_s, old_e, "work_calls", "user_confirmed")]
    new_key = _key("2024-01-15T11:00:00+00:00", "2024-01-15T11:20:00+00:00")
    t, src = _carry_user_tag_from_prior_intervals(
        started_at=new_s,
        ended_at=new_e,
        exact_key=new_key,
        exact_map={},
        prior_intervals=prior,
    )
    assert t is None
    assert src is None
