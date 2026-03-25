from tracking.cohort_insight import build_cohort_insight


def test_cohort_off_when_not_requested():
    en, band, _ = build_cohort_insight(
        include_requested=False,
        user_opt_in=True,
        stress_index=0.5,
        age_years=30,
    )
    assert en is False
    assert band is None


def test_cohort_off_when_not_opt_in():
    en, band, disc = build_cohort_insight(
        include_requested=True,
        user_opt_in=False,
        stress_index=0.5,
        age_years=30,
    )
    assert en is False
    assert band is None
    assert "Not medical" in disc or "medical" in disc.lower()


def test_cohort_typical_band():
    en, band, _ = build_cohort_insight(
        include_requested=True,
        user_opt_in=True,
        stress_index=0.42,
        age_years=30,
    )
    assert en is True
    assert band == "typical"
