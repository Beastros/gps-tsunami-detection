"""
dyfi_checker.py -- USGS Did You Feel It (DYFI) integration
GPS Ionospheric Tsunami Detection Pipeline -- V7

Fetches DYFI crowdsourced data from the USGS event detail geojson.
Small confidence contribution as a fast pre-TEC corroboration channel.
Available 5-15 min post-quake, before ShakeMap moment tensor is finalized.

Confidence contribution:
  +0.04  if num_responses >= 50 AND maxmmi >= 6.0
  +0.02  if num_responses >= 20 AND maxmmi >= 5.0
   0.00  otherwise (fail-open -- no DYFI data = no penalty, no abstain)

Population bias: DYFI reports skew toward US/Japan/NZ.
Remote Pacific events will have low counts regardless of magnitude.
Contribution abstains (returns 0) below 20 responses rather than penalizing.
"""
import requests
import logging

log = logging.getLogger(__name__)

USGS_DETAIL_URL = (
    "https://earthquake.usgs.gov/earthquakes/feed/v1.0/detail/{usgs_id}.geojson"
)


def get_dyfi_contribution(usgs_id):
    """
    Fetch DYFI data for a USGS event ID and return a confidence contribution.

    Parameters
    ----------
    usgs_id : str
        USGS event ID (e.g. "us7000abcd")

    Returns
    -------
    tuple: (dyfi_contrib, dyfi_responses, dyfi_maxmmi, dyfi_confirmed)
        dyfi_contrib   : float -- 0.00, 0.02, or 0.04
        dyfi_responses : int or None -- number of felt reports
        dyfi_maxmmi    : float or None -- max Modified Mercalli Intensity
        dyfi_confirmed : bool -- True if contribution > 0
    """
    try:
        url = USGS_DETAIL_URL.format(usgs_id=usgs_id)
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            log.warning("DYFI HTTP %d for %s -- fail open", r.status_code, usgs_id)
            return 0.0, None, None, False

        data = r.json()
        products = data.get("properties", {}).get("products", {})
        dyfi_list = products.get("dyfi", [])

        if not dyfi_list:
            log.info("DYFI no product for %s -- fail open", usgs_id)
            return 0.0, None, None, False

        props = dyfi_list[0].get("properties", {})

        try:
            num_responses = int(props.get("num-responses", 0) or 0)
        except (ValueError, TypeError):
            num_responses = 0

        try:
            maxmmi = float(props.get("maxmmi", 0) or 0)
        except (ValueError, TypeError):
            maxmmi = 0.0

        log.info(
            "DYFI %s responses=%d maxmmi=%.1f",
            usgs_id, num_responses, maxmmi,
        )

        if num_responses >= 50 and maxmmi >= 6.0:
            log.info("DYFI %s HIGH +0.04", usgs_id)
            return 0.04, num_responses, maxmmi, True
        elif num_responses >= 20 and maxmmi >= 5.0:
            log.info("DYFI %s LOW +0.02", usgs_id)
            return 0.02, num_responses, maxmmi, True
        else:
            log.info("DYFI %s below threshold -- no contribution", usgs_id)
            return 0.0, num_responses, maxmmi, False

    except Exception as e:
        log.warning("DYFI exception %s: %s -- fail open", usgs_id, str(e))
        return 0.0, None, None, False
