"""
This repository is public. .githooks/check_private_data.py refuses secrets,
credentials and the unreleased launch list at commit and push time; this runs
it over every tracked file as part of the suite, and checks that it still
recognises what it is there to catch. The fake credentials are assembled at
runtime, so this file never holds one.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_CHECK = Path(__file__).resolve().parents[2] / ".githooks" / "check_private_data.py"
if not _CHECK.exists():
    pytest.skip(".githooks/check_private_data.py not present in this checkout", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("check_private_data", _CHECK)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)


def kinds(text, path="backend/example.py", needles=()):
    return {kind for _, kind in check.findings_in_file(path, text.encode(), needles)}


def test_no_tracked_file_holds_private_data():
    result = subprocess.run([sys.executable, str(_CHECK), "--tree"], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("line, kind", [
    ("token = '" + "shp" + "at_" + "0123456789abcdef" * 2 + "'", "a Shopify access token"),
    ("-----BEGIN " + "RSA PRIVATE KEY-----", "a private key"),
    ("key = '" + "sk-" + "ant-" + "Zx81Qw" * 6 + "'", "an Anthropic or OpenAI key"),
    ("SERVER_KEY = \"" + "q7Rk2Vx9Lm4Tz8Wp1Ns6Hd3Fb5Jc0Ga" + "\"", "a hard-coded secret"),
    ("see https://docs.google.com/" + "spreadsheets/d/1AbC", "a link to a Google document"),
    ("\"sku\": \"" + "ZZ00" + "-DRS-D999-ABC-XYZ\"", "a brand SKU"),
])
def test_credentials_and_brand_data_are_recognised(line, kind):
    assert kind in kinds(line)


def test_unreleased_names_are_recognised_in_any_case_and_as_handles():
    needles = [("Silk Example Dress", "an unreleased style name", False),
               ("silk-example-dress", "an unreleased style name", False),
               ("s3cr3t-value-0042", "the value of X from shopify/private/secrets.env", True)]
    assert kinds("title: SILK EXAMPLE DRESS", needles=needles) == {"an unreleased style name"}
    assert kinds("/products/silk-example-dress", needles=needles) == {"an unreleased style name"}
    assert kinds("x = 's3cr3t-value-0042'", needles=needles) == {"the value of X from shopify/private/secrets.env"}


@pytest.mark.parametrize("path", ["shopify/private/secrets.env", "backend/intake_sessions.db", ".env",
                                  "backend/.env.production", "planning_documents/plan.md", "certs/shop.pem"])
def test_private_files_are_refused_whatever_they_hold(path):
    assert check.findings_in_file(path, b"", [])


def test_ordinary_code_and_test_values_pass():
    assert not kinds('THEME_SECRET = "test-theme-secret"\n'
                     'headers = {"X-MyStyle-Customer": token(customer_id="1001")}\n'
                     '"sku": "TS99-DRS-D901-SLK-BRN"\n'
                     'value = os.environ.get("MYSTYLE_SERVER_KEY", "")\n')
    assert not check.findings_in_file(".env.example", b"MYSTYLE_THEME_SECRET=", [])
    # The cached copy of the live store's products.json holds its public SKUs.
    assert not check.findings_in_file("backend/catalog_source.json", b'{"sku": "' + b"SL25" + b'-TOP-T001-CDC-BLK"}', [])
