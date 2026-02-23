# core/tenants/country_utils.py

import pycountry
import pytz
from babel import Locale

def get_country_details(country_code: str):
    """
    Auto-detects:
      - country_name
      - currency (ISO 4217)
      - timezone (primary)
      - locale (EN-first unless strictly French-only)

    SPECIAL: CFA Franc Zone → XAF or XOF correctly.
    """

    # Normalize
    country_code = country_code.upper()

    # ------------------------------------------------------------------
    # 1. Country lookup
    # ------------------------------------------------------------------
    country = pycountry.countries.get(alpha_2=country_code)
    if not country:
        raise ValueError(f"Invalid ISO country code: {country_code}")

    # ------------------------------------------------------------------
    # 2. Currency detection (FIXED for Africa CFA zones)
    # ------------------------------------------------------------------

    # Central African CFA Franc (XAF) countries
    XAF_ZONE = {"CM", "CF", "TD", "CG", "GA", "GQ"}

    # West African CFA Franc (XOF) countries
    XOF_ZONE = {"BJ", "BF", "CI", "GW", "ML", "NE", "SN", "TG"}

    if country_code in XAF_ZONE:
        currency_code = "XAF"
    elif country_code in XOF_ZONE:
        currency_code = "XOF"
    else:
        # fallback to pycountry lookup
        currency = None
        try:
            currency = pycountry.currencies.get(numeric=country.numeric)
        except Exception:
            pass

        currency_code = currency.alpha_3 if currency else "USD"  # global fallback

    # ------------------------------------------------------------------
    # 3. Locale inference (EN first unless French-only)
    # ------------------------------------------------------------------
    french_only_countries = XOF_ZONE.union({
        # Non-CFA French-only countries
        "FR", "CD", "CG", "GA", "CF"
    })

    if country_code in french_only_countries:
        lang = "fr"
    else:
        lang = "en"   # universal default

    try:
        locale = Locale.parse(f"{lang}_{country_code}")
    except Exception:
        locale = Locale.parse("en_US")

    # ------------------------------------------------------------------
    # 4. Timezone inference
    # ------------------------------------------------------------------
    timezones = pytz.country_timezones.get(country_code, [])
    timezone = timezones[0] if timezones else "UTC"

    # ------------------------------------------------------------------
    # 5. Final structured output
    # ------------------------------------------------------------------
    return {
        "country_name": country.name,
        "currency": currency_code,
        "timezone": timezone,
        "locale": str(locale)
    }
