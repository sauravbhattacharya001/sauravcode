"""Tests for date arithmetic built-in functions."""
import subprocess
import sys
import os
import tempfile

INTERPRETER = os.path.join(os.path.dirname(__file__), '..', 'saurav.py')


def run_srv(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True, timeout=10
        )
    os.unlink(f.name)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())
    return result.stdout.strip()


def run_srv_error(code):
    with tempfile.NamedTemporaryFile(mode='w', suffix='.srv', delete=False) as f:
        f.write(code)
        f.flush()
        result = subprocess.run(
            [sys.executable, INTERPRETER, f.name],
            capture_output=True, text=True, timeout=10
        )
    os.unlink(f.name)
    return result


class TestDateAdd:
    def test_add_days(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 5 "days"') == "2026-01-20T10:00:00"

    def test_add_hours(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 3 "hours"') == "2026-01-15T13:00:00"

    def test_add_minutes(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 90 "minutes"') == "2026-01-15T11:30:00"

    def test_add_seconds(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 30 "seconds"') == "2026-01-15T10:00:30"

    def test_add_weeks(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 2 "weeks"') == "2026-01-29T10:00:00"

    def test_subtract_days(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" (0 - 3) "days"') == "2026-01-12T10:00:00"

    def test_subtract_hours(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" (0 - 2) "hours"') == "2026-01-15T08:00:00"

    def test_cross_midnight(self):
        assert run_srv('print date_add "2026-01-15T23:30:00" 2 "hours"') == "2026-01-16T01:30:00"

    def test_cross_month(self):
        assert run_srv('print date_add "2026-01-30T12:00:00" 3 "days"') == "2026-02-02T12:00:00"

    def test_cross_year(self):
        assert run_srv('print date_add "2026-12-30T12:00:00" 5 "days"') == "2027-01-04T12:00:00"

    def test_unit_abbreviation_d(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 1 "d"') == "2026-01-16T10:00:00"

    def test_unit_abbreviation_h(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 1 "h"') == "2026-01-15T11:00:00"

    def test_unit_abbreviation_min(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 30 "min"') == "2026-01-15T10:30:00"

    def test_unit_abbreviation_s(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 45 "s"') == "2026-01-15T10:00:45"

    def test_unit_abbreviation_w(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 1 "w"') == "2026-01-22T10:00:00"

    def test_singular_unit(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 1 "day"') == "2026-01-16T10:00:00"

    def test_fractional_hours(self):
        assert run_srv('print date_add "2026-01-15T10:00:00" 1.5 "hours"') == "2026-01-15T11:30:00"

    def test_date_only_input(self):
        assert run_srv('print date_add "2026-01-15" 1 "days"') == "2026-01-16T00:00:00"

    def test_with_variable(self):
        code = 'start = "2026-01-15T10:00:00"\nresult = date_add (start) 5 "days"\nprint result'
        assert run_srv(code) == "2026-01-20T10:00:00"

    def test_invalid_date_string(self):
        r = run_srv_error('print date_add "not-a-date" 1 "days"')
        assert r.returncode != 0

    def test_invalid_unit(self):
        r = run_srv_error('print date_add "2026-01-15" 1 "fortnights"')
        assert r.returncode != 0

    def test_wrong_arg_count(self):
        r = run_srv_error('print date_add "2026-01-15" 1')
        assert r.returncode != 0

    def test_non_numeric_amount(self):
        r = run_srv_error('print date_add "2026-01-15" "five" "days"')
        assert r.returncode != 0


class TestDateDiff:
    def test_diff_days_positive(self):
        assert float(run_srv('print date_diff "2026-01-20T10:00:00" "2026-01-15T10:00:00" "days"')) == 5.0

    def test_diff_days_negative(self):
        assert float(run_srv('print date_diff "2026-01-15T10:00:00" "2026-01-20T10:00:00" "days"')) == -5.0

    def test_diff_hours(self):
        assert float(run_srv('print date_diff "2026-01-15T15:00:00" "2026-01-15T10:00:00" "hours"')) == 5.0

    def test_diff_minutes(self):
        assert float(run_srv('print date_diff "2026-01-15T10:30:00" "2026-01-15T10:00:00" "minutes"')) == 30.0

    def test_diff_seconds(self):
        assert float(run_srv('print date_diff "2026-01-15T10:00:45" "2026-01-15T10:00:00" "seconds"')) == 45.0

    def test_diff_weeks(self):
        assert float(run_srv('print date_diff "2026-01-29T10:00:00" "2026-01-15T10:00:00" "weeks"')) == 2.0

    def test_diff_same_date(self):
        assert float(run_srv('print date_diff "2026-01-15T10:00:00" "2026-01-15T10:00:00" "days"')) == 0.0

    def test_diff_cross_month(self):
        assert float(run_srv('print date_diff "2026-02-01T00:00:00" "2026-01-30T00:00:00" "days"')) == 2.0

    def test_diff_fractional(self):
        assert float(run_srv('print date_diff "2026-01-15T12:00:00" "2026-01-15T00:00:00" "days"')) == 0.5

    def test_diff_unit_abbreviation(self):
        assert float(run_srv('print date_diff "2026-01-16T10:00:00" "2026-01-15T10:00:00" "d"')) == 1.0

    def test_with_variable(self):
        code = 'later = date_add "2026-03-01T12:00:00" 5 "days"\nresult = date_diff (later) "2026-03-01T12:00:00" "days"\nprint result'
        assert float(run_srv(code)) == 5.0

    def test_invalid_unit(self):
        r = run_srv_error('print date_diff "2026-01-15" "2026-01-10" "months"')
        assert r.returncode != 0

    def test_invalid_date(self):
        r = run_srv_error('print date_diff "bad" "2026-01-10" "days"')
        assert r.returncode != 0


class TestDateCompare:
    def test_a_before_b(self):
        assert float(run_srv('print date_compare "2026-01-10T00:00:00" "2026-01-15T00:00:00"')) == -1.0

    def test_a_after_b(self):
        assert float(run_srv('print date_compare "2026-01-20T00:00:00" "2026-01-15T00:00:00"')) == 1.0

    def test_equal_dates(self):
        assert float(run_srv('print date_compare "2026-01-15T10:00:00" "2026-01-15T10:00:00"')) == 0.0

    def test_date_only(self):
        assert float(run_srv('print date_compare "2026-01-10" "2026-01-15"')) == -1.0

    def test_invalid_date(self):
        r = run_srv_error('print date_compare "bad" "2026-01-10"')
        assert r.returncode != 0

    def test_wrong_arg_count(self):
        r = run_srv_error('print date_compare "2026-01-10"')
        assert r.returncode != 0

    def test_conditional(self):
        code = 'cmp = date_compare "2026-01-10" "2026-01-15"\nif cmp < 0\n  print "earlier"'
        assert run_srv(code) == "earlier"

    def test_compare_with_add_result(self):
        code = 'later = date_add "2026-06-15T10:00:00" 1 "hours"\nresult = date_compare (later) "2026-06-15T10:00:00"\nprint result'
        assert float(run_srv(code)) == 1.0


class TestDateRange:
    def test_daily_range(self):
        code = 'dates = date_range "2026-01-15" "2026-01-18" 1 "days"\nfor d in dates\n  print d'
        lines = run_srv(code).strip().split('\n')
        assert len(lines) == 3
        assert lines[0] == "2026-01-15T00:00:00"
        assert lines[2] == "2026-01-17T00:00:00"

    def test_hourly_range(self):
        out = run_srv('print date_range "2026-01-15T10:00:00" "2026-01-15T13:00:00" 1 "hours"')
        assert "2026-01-15T10:00:00" in out
        assert "2026-01-15T12:00:00" in out
        assert "2026-01-15T13:00:00" not in out

    def test_weekly_range_len(self):
        code = 'dates = date_range "2026-01-01" "2026-01-22" 1 "weeks"\nprint len (dates)'
        assert float(run_srv(code)) == 3.0

    def test_range_length(self):
        code = 'dates = date_range "2026-01-01" "2026-01-06" 1 "days"\nprint len (dates)'
        assert float(run_srv(code)) == 5.0

    def test_start_equals_end_empty(self):
        code = 'dates = date_range "2026-01-15" "2026-01-15" 1 "days"\nprint len (dates)'
        assert float(run_srv(code)) == 0.0

    def test_start_after_end_empty(self):
        code = 'dates = date_range "2026-01-20" "2026-01-15" 1 "days"\nprint len (dates)'
        assert float(run_srv(code)) == 0.0

    def test_reverse_range(self):
        code = 'dates = date_range "2026-01-18" "2026-01-15" (0 - 1) "days"\nfor d in dates\n  print d'
        lines = run_srv(code).strip().split('\n')
        assert len(lines) == 3
        assert lines[0] == "2026-01-18T00:00:00"
        assert lines[2] == "2026-01-16T00:00:00"

    def test_step_two_days(self):
        code = 'dates = date_range "2026-01-01" "2026-01-07" 2 "days"\nprint len (dates)'
        assert float(run_srv(code)) == 3.0

    def test_zero_step_error(self):
        r = run_srv_error('print date_range "2026-01-01" "2026-01-05" 0 "days"')
        assert r.returncode != 0

    def test_invalid_unit(self):
        r = run_srv_error('print date_range "2026-01-01" "2026-01-05" 1 "years"')
        assert r.returncode != 0

    def test_non_numeric_step(self):
        r = run_srv_error('print date_range "2026-01-01" "2026-01-05" "one" "days"')
        assert r.returncode != 0

    def test_fractional_step(self):
        code = 'dates = date_range "2026-01-15T00:00:00" "2026-01-15T03:00:00" 1.5 "hours"\nprint len (dates)'
        assert float(run_srv(code)) == 2.0


class TestDateArithmeticIntegration:
    def test_add_then_diff(self):
        code = 'end_d = date_add "2026-03-01T12:00:00" 5 "days"\nresult = date_diff (end_d) "2026-03-01T12:00:00" "days"\nprint result'
        assert float(run_srv(code)) == 5.0

    def test_range_with_format(self):
        code = 'dates = date_range "2026-01-01" "2026-01-04" 1 "days"\nfor d in dates\n  print date_format (d) "%A"'
        lines = run_srv(code).strip().split('\n')
        assert lines[0] == "Thursday"
        assert lines[1] == "Friday"
        assert lines[2] == "Saturday"

    def test_countdown(self):
        assert float(run_srv('print date_diff "2026-12-25" "2026-12-20" "days"')) == 5.0

    def test_range_with_date_part(self):
        code = 'dates = date_range "2026-03-01" "2026-03-04" 1 "days"\nfor d in dates\n  print date_part (d) "day"'
        lines = run_srv(code).strip().split('\n')
        assert float(lines[0]) == 1.0
        assert float(lines[2]) == 3.0

    def test_business_hours(self):
        code = 'hours = date_range "2026-01-15T09:00:00" "2026-01-15T17:00:00" 1 "hours"\nprint len (hours)'
        assert float(run_srv(code)) == 8.0

    def test_add_preserves_time(self):
        code = 'result = date_add "2026-01-15T14:30:45" 7 "days"\nprint date_part (result) "hour"\nprint date_part (result) "minute"\nprint date_part (result) "second"'
        lines = run_srv(code).strip().split('\n')
        assert float(lines[0]) == 14.0
        assert float(lines[1]) == 30.0
        assert float(lines[2]) == 45.0

    def test_chain_adds(self):
        code = 'step1 = date_add "2026-01-01T00:00:00" 1 "days"\nstep2 = date_add (step1) 2 "hours"\nstep3 = date_add (step2) 30 "minutes"\nprint step3'
        assert run_srv(code) == "2026-01-02T02:30:00"

    def test_diff_alias(self):
        assert float(run_srv('print date_diff "2026-01-15T12:00:00" "2026-01-15T10:00:00" "h"')) == 2.0
