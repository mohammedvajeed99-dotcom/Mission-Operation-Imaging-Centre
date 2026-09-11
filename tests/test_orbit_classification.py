"""Unit tests for the sun-synchronous orbit classifier
(core.constellation_analytics._classify_orbit_type / _nodal_precession_deg_per_day)
and the UTC timestamp helper (core.time_utils.utc_iso).

Run with:
    python -m unittest tests.test_orbit_classification -v

The classifier used to call any inclination in 95-103 deg "Sun-Synchronous
Orbit (SSO)" regardless of altitude -- physically wrong, since the same
inclination is only actually sun-synchronous at one specific altitude (for
a circular orbit). These tests exist specifically to catch that class of
regression: an inclination that LOOKS SSO-shaped must still be rejected if
the real nodal precession rate at that altitude doesn't match Earth's.
"""

import datetime as dtm
import unittest

import pandas as pd

from core.constellation_analytics import (
    EARTH_SOLAR_RATE_DEG_DAY,
    _classify_orbit_type,
    _nodal_precession_deg_per_day,
)
from core.time_utils import utc_iso

# This mission's real configured values (Mission_Configuration.xlsx), used
# as fixed points so these tests are checkable against the actual missions
# in this project, not just internally self-consistent.
ASC074_INCLINATION_DEG = 50.0
ASC080_INCLINATION_DEG = 97.54
MISSION_ALTITUDE_KM = 536.0


class NodalPrecessionTests(unittest.TestCase):
    def test_asc080_real_mission_is_genuinely_sun_synchronous(self):
        # Not just "inclination looks SSO-shaped" -- the real J2 precession
        # rate at this mission's real altitude must match Earth's solar
        # rate to within the classifier's own tolerance.
        rate = _nodal_precession_deg_per_day(MISSION_ALTITUDE_KM, ASC080_INCLINATION_DEG)
        self.assertAlmostEqual(rate, EARTH_SOLAR_RATE_DEG_DAY, delta=0.05)

    def test_asc074_real_mission_is_nowhere_near_sun_synchronous(self):
        rate = _nodal_precession_deg_per_day(MISSION_ALTITUDE_KM, ASC074_INCLINATION_DEG)
        self.assertGreater(abs(rate - EARTH_SOLAR_RATE_DEG_DAY), 1.0)

    def test_prograde_orbit_precesses_westward_retrograde_eastward(self):
        # A textbook, independently-checkable fact about J2 nodal drift:
        # prograde orbits (i < 90) drift negative (westward), retrograde
        # orbits (i > 90) drift positive (eastward) -- this is *why* real
        # SSOs are always retrograde, not an arbitrary implementation detail.
        prograde = _nodal_precession_deg_per_day(700.0, 45.0)
        retrograde = _nodal_precession_deg_per_day(700.0, 135.0)
        self.assertLess(prograde, 0)
        self.assertGreater(retrograde, 0)


class ClassifyOrbitTypeTests(unittest.TestCase):
    def test_real_asc080_mission_classifies_as_sso(self):
        self.assertEqual(
            _classify_orbit_type(ASC080_INCLINATION_DEG, MISSION_ALTITUDE_KM),
            "Sun-Synchronous Orbit (SSO)",
        )

    def test_real_asc074_mission_classifies_as_prograde_inclined_leo(self):
        self.assertEqual(
            _classify_orbit_type(ASC074_INCLINATION_DEG, MISSION_ALTITUDE_KM),
            "Prograde Inclined LEO",
        )

    def test_sso_shaped_inclination_at_wrong_altitude_is_not_called_sso(self):
        # The exact anti-pattern this classifier used to have: 97.5 deg is
        # "SSO-shaped" by the old bare inclination-range check, but at 1200
        # km it precesses nowhere near the required rate and must not be
        # called sun-synchronous.
        result = _classify_orbit_type(97.5, 1200.0)
        self.assertNotEqual(result, "Sun-Synchronous Orbit (SSO)")

    def test_polar_orbit_classified_when_no_altitude_given(self):
        # Without an altitude, precession can't be computed -- falls back
        # to the inclination-only bands rather than guessing SSO.
        self.assertEqual(_classify_orbit_type(90.0, None), "Polar Orbit")

    def test_none_inclination_is_not_configured(self):
        self.assertEqual(_classify_orbit_type(None, 536.0), "Not Configured")

    def test_prograde_and_retrograde_bands_without_altitude(self):
        self.assertEqual(_classify_orbit_type(45.0, None), "Prograde Inclined LEO")
        self.assertEqual(_classify_orbit_type(135.0, None), "Retrograde Inclined LEO")


class UtcIsoTests(unittest.TestCase):
    def test_naive_datetime_gets_explicit_utc_offset(self):
        # This is the actual bug: a naive value's isoformat() omits any
        # offset, which a JS `new Date(...)` on the receiving end parses as
        # *local time*, not UTC -- utc_iso() must always attach +00:00.
        naive = dtm.datetime(2026, 7, 4, 0, 0, 0)
        self.assertEqual(utc_iso(naive), "2026-07-04T00:00:00+00:00")

    def test_naive_pandas_timestamp_gets_explicit_utc_offset(self):
        naive = pd.Timestamp("2026-07-03 00:00:00")
        self.assertEqual(utc_iso(naive), "2026-07-03T00:00:00+00:00")

    def test_already_aware_datetime_is_left_correct(self):
        aware = dtm.datetime(2026, 1, 1, tzinfo=dtm.timezone.utc)
        self.assertEqual(utc_iso(aware), "2026-01-01T00:00:00+00:00")

    def test_none_returns_none(self):
        self.assertIsNone(utc_iso(None))


if __name__ == "__main__":
    unittest.main()
