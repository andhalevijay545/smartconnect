"""
Pure-logic tests: no database, no web server.  They only need Flask installed.

Covers: input validation, QR token security helpers, time/period helpers,
IP classification (LAN vs WAN), CSV-injection protection, rate limiting and the
privacy rules of the serializers.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.utils import helpers, ratelimit, tokens, validators
from app.utils.serializers import visitor_brief, visitor_dict

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 24, 10, 0, 0)  # naive UTC, like every timestamp in the database


# ----------------------------------------------------------------- validators
class TestValidators:
    @pytest.mark.parametrize("value", ["Asha Patil", "Mary-Anne O'Neil", "Dr. A. P. J. Kalam"])
    def test_full_name_ok(self, value):
        assert validators.validate_full_name(value)[1] is None

    @pytest.mark.parametrize("value", ["", "A", "R2D2", "<script>", "12345", None, 42])
    def test_full_name_bad(self, value):
        assert validators.validate_full_name(value)[0] is None

    def test_full_name_collapses_spaces(self):
        assert validators.validate_full_name("  Asha    Patil ")[0] == "Asha Patil"

    @pytest.mark.parametrize("raw,clean", [("9876543210", "9876543210"),
                                           ("+91 98765-43210", "+919876543210"),
                                           ("(987) 654 3210", "9876543210")])
    def test_mobile_ok(self, raw, clean):
        assert validators.validate_mobile(raw) == (clean, None)

    @pytest.mark.parametrize("raw", ["12345", "abcdefghij", "98765432101234567", "", None])
    def test_mobile_bad(self, raw):
        assert validators.validate_mobile(raw)[0] is None

    def test_email(self):
        assert validators.validate_email("  Asha@Example.COM ") == ("asha@example.com", None)
        for bad in ("asha", "asha@", "@example.com", "a b@example.com", "a@b", None):
            assert validators.validate_email(bad)[0] is None

    def test_password_rules(self):
        assert validators.validate_password("Strong@123")[1] is None
        for bad in ("short1A", "alllowercase1", "ALLUPPERCASE1", "NoDigitsHere", None):
            assert validators.validate_password(bad)[0] is None

    def test_username(self):
        assert validators.validate_username(" Guard.One ") == ("guard.one", None)
        assert validators.validate_username("a b")[0] is None
        assert validators.validate_username("ab")[0] is None

    def test_int_id(self):
        assert validators.validate_int_id("7", "x") == (7, None)
        for bad in (0, -3, "abc", None, True):
            assert validators.validate_int_id(bad, "x")[0] is None


def _payload(**over):
    data = {"full_name": "Asha Patil", "mobile": "9876543210", "email": "asha@example.com",
            "address": "12 MG Road, Pune", "purpose": "Meeting", "department_id": 1, "host_id": 1,
            "expected_at": (NOW + timedelta(hours=2)).isoformat() + "Z"}
    data.update(over)
    return data


class TestVisitorPayload:
    def test_valid(self):
        clean, errors = validators.validate_visitor_payload(_payload(), NOW)
        assert errors == {}
        assert clean["mobile"] == "9876543210"
        assert clean["expected_at"] == NOW + timedelta(hours=2)  # stored as naive UTC

    def test_every_field_is_checked(self):
        _, errors = validators.validate_visitor_payload({}, NOW)
        assert set(errors) == {"full_name", "mobile", "email", "address", "purpose",
                               "department_id", "host_id", "expected_at"}

    def test_past_and_far_future_dates_rejected(self):
        past = (NOW - timedelta(days=1)).isoformat() + "Z"
        far = (NOW + timedelta(days=200)).isoformat() + "Z"
        assert "expected_at" in validators.validate_visitor_payload(_payload(expected_at=past), NOW)[1]
        assert "expected_at" in validators.validate_visitor_payload(_payload(expected_at=far), NOW)[1]
        assert "expected_at" in validators.validate_visitor_payload(_payload(expected_at="tomorrow"), NOW)[1]

    def test_naive_time_uses_given_timezone(self):
        clean, errors = validators.validate_visitor_payload(
            _payload(expected_at="2026-11-24T18:00:00"), NOW, IST)
        assert errors == {}
        assert clean["expected_at"] == datetime(2026, 11, 24, 12, 30)  # 18:00 IST == 12:30 UTC

    def test_control_characters_rejected(self):
        _, errors = validators.validate_visitor_payload(_payload(purpose="Meet\x00ing"), NOW)
        assert "purpose" in errors

    def test_not_a_json_object(self):
        assert validators.validate_visitor_payload(["x"], NOW)[1] == {"_": "JSON object expected."}


# --------------------------------------------------------------------- tokens
class TestTokens:
    def test_tokens_are_unique_and_long(self):
        batch = {tokens.new_token() for _ in range(200)}
        assert len(batch) == 200
        assert all(len(t) >= 43 for t in batch)

    def test_hash_is_deterministic_and_keyed(self):
        t = tokens.new_token()
        assert tokens.hash_token(t, "pepper") == tokens.hash_token(t, "pepper")
        assert tokens.hash_token(t, "pepper") != tokens.hash_token(t, "other-pepper")
        assert len(tokens.hash_token(t, "pepper")) == 64
        assert t not in tokens.hash_token(t, "pepper")  # the secret is not recoverable from the hash

    def test_payload_contains_only_prefix_and_token(self):
        t = tokens.new_token()
        text = tokens.qr_payload(t)
        assert text == "SMARTCONNECT:v1:" + t

    def test_extract_token(self):
        t = tokens.new_token()
        assert tokens.extract_token(tokens.qr_payload(t)) == t
        assert tokens.extract_token("  " + t + "\n") == t          # whitespace from scanners
        for bad in ("", "short", "has space " + "a" * 40, "x" * 200, None, 12345):
            assert tokens.extract_token(bad) is None

    def test_operation_and_device_ids(self):
        assert tokens.valid_operation_id("op-1234abcd")
        for bad in ("short", "has space 1234", "x" * 65, None, 123):
            assert not tokens.valid_operation_id(bad)
        assert tokens.clean_device_id("phone-0001-abc", "fallback") == "phone-0001-abc"
        assert tokens.clean_device_id("bad id!", "fallback") == "fallback"
        assert tokens.clean_device_id(None, "fallback") == "fallback"

    def test_access_key_is_random(self):
        assert tokens.new_access_key() != tokens.new_access_key()


# -------------------------------------------------------------- time helpers
class TestTime:
    def test_utcnow_is_naive(self):
        assert helpers.utcnow().tzinfo is None

    def test_iso_roundtrip(self):
        assert helpers.iso(datetime(2026, 1, 2, 3, 4, 5, 999)) == "2026-01-02T03:04:05Z"
        assert helpers.iso(None) is None
        assert helpers.parse_iso_dt("2026-01-02T03:04:05Z") == datetime(2026, 1, 2, 3, 4, 5)

    def test_parse_converts_offsets(self):
        assert helpers.parse_iso_dt("2026-01-02T08:34:05+05:30") == datetime(2026, 1, 2, 3, 4, 5)

    @pytest.mark.parametrize("bad", [None, "", "   ", "not a date", 5])
    def test_parse_rejects_garbage(self, bad):
        assert helpers.parse_iso_dt(bad) is None

    def test_local_day_bounds(self):
        start, end = helpers.local_day_bounds(date(2026, 11, 24), IST)
        assert start == datetime(2026, 11, 23, 18, 30)
        assert end == datetime(2026, 11, 24, 18, 30)

    def test_period_bounds(self):
        _, _, _, first, last = helpers.period_bounds("weekly", date(2026, 11, 25), IST)  # a Wednesday
        assert (first, last) == (date(2026, 11, 23), date(2026, 11, 29))       # Monday..Sunday
        _, _, _, first, last = helpers.period_bounds("monthly", date(2028, 2, 10), IST)
        assert (first, last) == (date(2028, 2, 1), date(2028, 2, 29))          # leap year
        _, _, _, first, last = helpers.period_bounds("daily", date(2026, 11, 24), IST)
        assert first == last == date(2026, 11, 24)
        with pytest.raises(ValueError):
            helpers.period_bounds("yearly", date(2026, 1, 1), IST)

    def test_get_tz_falls_back_to_utc(self):
        assert helpers.get_tz("Not/AZone") == timezone.utc


# ----------------------------------------------------------- network helpers
class TestNetworkHelpers:
    @pytest.mark.parametrize("ip", ["192.168.1.20", "10.0.0.5", "172.16.4.4", "127.0.0.1",
                                    "169.254.1.1", "::1"])
    def test_private_addresses_are_lan(self, ip):
        assert helpers.classify_ip(ip) == "LAN"

    @pytest.mark.parametrize("ip", ["8.8.8.8", "1.1.1.1", "2001:4860:4860::8888"])
    def test_public_addresses_are_wan(self, ip):
        assert helpers.classify_ip(ip) == "WAN"

    def test_bad_address(self):
        assert helpers.classify_ip("not-an-ip") == "UNKNOWN"
        assert helpers.classify_ip("") == "UNKNOWN"

    def test_lan_ips_never_include_loopback(self):
        assert all(not ip.startswith("127.") for ip in helpers.get_lan_ips())


# ------------------------------------------------------------------ privacy
class TestPrivacy:
    def test_csv_injection_is_neutralised(self):
        for dangerous in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\tcell"):
            assert helpers.csv_safe(dangerous).startswith("'")
        assert helpers.csv_safe("Normal text") == "Normal text"
        assert helpers.csv_safe(42) == 42

    def test_mobile_masking(self):
        assert helpers.mask_mobile("9876543210") == "******3210"
        assert helpers.mask_mobile("") == ""

    def _visitor(self):
        return SimpleNamespace(
            public_id="abc123", full_name="Asha Patil", mobile="9876543210", email="asha@example.com",
            address="12 MG Road", purpose="Meeting", department=SimpleNamespace(name="Engineering"),
            host=SimpleNamespace(full_name="Priya Sharma"), host_id=1, department_id=1,
            expected_at=NOW, status="PENDING", created_at=NOW, visits=[], approval=None, passes=[])

    def test_security_staff_get_masked_contact_details(self):
        data = visitor_dict(self._visitor(), "security")
        assert data["mobile"] == "******3210"
        assert "email" not in data and "address" not in data

    def test_admin_host_and_visitor_see_everything(self):
        for role in ("admin", "host", "visitor"):
            data = visitor_dict(self._visitor(), role)
            assert data["mobile"] == "9876543210"
            assert data["email"] == "asha@example.com"

    def test_realtime_payload_has_no_contact_details(self):
        brief = visitor_brief(self._visitor())
        blob = repr(brief)
        assert "9876543210" not in blob and "asha@example.com" not in blob and "MG Road" not in blob


# --------------------------------------------------------------- rate limiting
class TestRateLimit:
    def test_sliding_window(self):
        lim = ratelimit.SlidingWindowLimiter()
        assert all(lim.allow("ip", 3, 60, now=t) for t in (0, 1, 2))
        assert lim.allow("ip", 3, 60, now=3) is False          # 4th hit inside the window
        assert lim.allow("other-ip", 3, 60, now=3) is True     # keys are independent
        assert lim.allow("ip", 3, 60, now=61) is True          # old hits expired

    def test_login_lockout(self):
        tracker = ratelimit.FailureTracker()
        for i in range(4):
            assert tracker.failure("k", 5, 300, now=i) is False
        assert tracker.failure("k", 5, 300, now=4) is True      # 5th failure locks
        assert tracker.locked_for("k", now=5) > 0
        assert tracker.locked_for("k", now=400) == 0            # lock expires
        assert tracker.locked_for("someone-else", now=5) == 0

    def test_success_resets_failures(self):
        tracker = ratelimit.FailureTracker()
        for i in range(4):
            tracker.failure("k", 5, 300, now=i)
        tracker.success("k")
        assert tracker.failure("k", 5, 300, now=10) is False
