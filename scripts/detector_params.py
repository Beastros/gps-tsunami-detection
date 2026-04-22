"""
FROZEN DETECTOR PARAMETERS
============================
These parameters are locked as of April 2025 and must not be
adjusted when validating on new events (Samoa 2009, Kuril 2006,
Sumatra 2004, additional control days).

This file is the canonical parameter reference for all subsequent
validation runs. Any change to these parameters after this date
invalidates the blind validation claim.

Physical justification for each parameter is documented below.
"""

# ── Detection threshold ───────────────────────────────────────────
SNR_THRESHOLD = 2.0         # sigma above pre-event noise floor
# Justification: 2.0σ provides sensitivity to weak far-field signals
# (Haida Gwaii MKEA SNR=2.1x). Quiet day test showed 0 false alarms
# at 2.5σ but marginal at 2.0σ (1 trigger). Coherence constraint
# compensates for the looser threshold.

MIN_DURATION_MIN = 3        # minimum sustained crossing duration
# Justification: 3 minutes = 6 samples at 30-sec resolution.
# Eliminates brief noise spikes. Tsunami AGW signals persist 10-40 min.

# ── Coherence speed constraint ────────────────────────────────────
TSUNAMI_SPEED_MIN_MS = 150  # m/s
TSUNAMI_SPEED_MAX_MS = 350  # m/s
# Justification: Open-ocean tsunami phase velocity = sqrt(g*d) where
# d = water depth. Pacific mean depth ~4000m → ~200 m/s.
# Range 150-350 accounts for depth variability (1000m shallow: 99 m/s,
# 6000m deep trench: 243 m/s) plus AGW upward propagation geometry.
# Seismic acoustic ~1000 m/s (rejected above 350).
# Diurnal enhancement ~0 m/s (rejected below 150, near-simultaneous).

# ── Timing constraints ────────────────────────────────────────────
MIN_POST_QUAKE_HOURS = 1.5  # hours after earthquake
# Justification: No tsunami can travel from source to Hawaii in <1.5h.
# Minimum Pacific propagation time at 350 m/s for nearest source
# (Aleutians, ~3000 km) = 2.4h. Set to 1.5h for conservative margin.
# Eliminates seismic acoustic coherence at t≈0.

MAX_POST_QUAKE_HOURS = 22.0 # hours after earthquake
# Justification: No tsunami signal expected >22h post-quake at Hawaii
# distances. Eliminates diurnal coherence at hours 16-20.

# ── TEC processing ────────────────────────────────────────────────
POLYNOMIAL_ORDER = 4        # detrending polynomial degree
BANDPASS_LO_MIN  = 10       # minutes (high-pass corner)
BANDPASS_HI_MIN  = 120      # minutes (low-pass corner)
MIN_ARC_EPOCHS   = 120      # minimum arc length (60 min at 30-sec)
ELEV_CUTOFF_DEG  = 20       # minimum satellite elevation angle
RESAMPLE_SEC     = 30       # output grid interval

# ── Network requirements ──────────────────────────────────────────
MIN_STATIONS     = 2        # minimum stations for coherence check
TIME_TOLERANCE_MIN = 10     # extra tolerance on inter-station delay

# ── Station coordinates (fixed, from IGS) ────────────────────────
STATIONS = {
    "mkea": {"lat": 19.801, "lon": -155.456, "alt": 3763,
             "name": "Mauna Kea HI"},
    "kokb": {"lat": 22.127, "lon": -159.665, "alt": 1167,
             "name": "Kokee Park Kauai HI"},
    "hnlc": {"lat": 21.297, "lon": -157.816, "alt":    5,
             "name": "Honolulu HI"},
    "guam": {"lat": 13.489, "lon":  144.868, "alt":   83,
             "name": "Guam"},
}

# ── Calibration model (far-field, locked) ────────────────────────
# wave_m = CALIB_A × TEC_TECU × 10^(CALIB_B × Mw) / dist_km^CALIB_C
CALIB_A = 2283.839
CALIB_B = 0.771
CALIB_C = 2.614
# Fitted on: Tōhoku 2011 (MKEA, HNLC), Chile 2010 (MKEA),
#            Haida Gwaii 2012 (MKEA, HNLC) — 5 points, 3 events
# r² = 0.824, RMSE = 0.171m
# Valid range: Mw 7.7-9.0, dist 4400-10900 km
# Status: PRELIMINARY — requires validation on additional events

# ── Version control ───────────────────────────────────────────────
PARAMETER_VERSION = "v1.0"
LOCKED_DATE       = "2025-04-22"
LOCKED_ON_EVENTS  = ["tohoku_2011", "haida_gwaii_2012", "chile_2010"]
CONTROLS_TESTED   = ["quiet_apr10_2011", "indian_ocean_apr11_2012"]

VALIDATION_LOG = [
    # Add entries as new events are tested (DO NOT change parameters)
    # Format: (date_tested, event, result, notes)
    ("2025-04-22", "tohoku_2011",        "TP", "GUAM-MKEA/KOKB, +7.6-8.2h, 155-215 m/s"),
    ("2025-04-22", "haida_gwaii_2012",   "TP", "MKEA-HNLC, +4.1h, 208 m/s"),
    ("2025-04-22", "chile_2010",         "TP", "MKEA-KOKB, +15.1h, 165 m/s"),
    ("2025-04-22", "quiet_apr10_2011",   "TN", "0 coherent pairs"),
    ("2025-04-22", "indian_ocean_2012",  "TN", "0 coherent pairs in window"),
    # --- BLIND VALIDATION BELOW THIS LINE ---
    # samoa_2009
    # kuril_2006
    # sumatra_2004
    # quiet control days x9
    # geomagnetic storm day x2
]
