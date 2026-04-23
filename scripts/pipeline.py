"""
GPS Tsunami Detector — Master Pipeline
========================================
Runs the full automated loop:
  1. Check USGS feed for new Pacific events
  2. Download RINEX for events ready (3h+ post-quake)
  3. Run frozen detector on downloaded data
  4. Score predictions against NOAA tide gauge (24h+ post-quake)
  5. Update running log

Usage:
  # Run once (manual trigger):
  python pipeline.py --once

  # Run continuously (every 15 min):
  python pipeline.py

  # Set up as Windows Task Scheduler job:
  # Action: python pipeline.py --once
  # Trigger: every 15 minutes

Environment variables needed:
  EARTHDATA_USER=mthhorn
  EARTHDATA_PASS=<your_password>

Or create a .env file with those lines (never commit to GitHub).
"""

import time
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

# Import pipeline modules
import usgs_listener
import rinex_downloader
import detector_runner
import scorer

LOG_FILE = "pipeline.log"
POLL_INTERVAL = 900  # 15 minutes

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

def run_pipeline():
    """Run one full pipeline cycle."""
    log.info(f"\n{'='*55}")
    log.info(f"PIPELINE CYCLE  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"{'='*55}")

    # Step 1: Check USGS feed
    log.info("\n[1/4] Checking USGS feed...")
    queue = usgs_listener.load_queue()
    new = usgs_listener.check_feed(queue)
    usgs_listener.save_queue(queue)
    log.info(f"  {new} new candidates")

    # Step 2: Download RINEX
    log.info("\n[2/4] Downloading RINEX...")
    rinex_downloader.main()

    # Step 3: Run detector
    log.info("\n[3/4] Running detector...")
    detector_runner.main()

    # Step 4: Score
    log.info("\n[4/4] Scoring predictions...")
    scorer.main()

    log.info("\nCycle complete.")

def main(once=False):
    log.info("="*55)
    log.info("GPS Tsunami Detector — Live Pipeline")
    log.info("Parameters frozen: 2025-04-22")
    log.info("github.com/Beastros/gps-tsunami-detection")
    log.info("="*55)

    # Create .env reminder if not present
    if not Path(".env").exists():
        log.warning("No .env file found. Create one with:")
        log.warning("  EARTHDATA_USER=mthhorn")
        log.warning("  EARTHDATA_PASS=your_nasa_earthdata_password")

    while True:
        try:
            run_pipeline()
        except Exception as e:
            log.error(f"Pipeline cycle error: {e}")
            import traceback; traceback.print_exc()

        if once:
            log.info("--once mode, done.")
            break

        log.info(f"\nSleeping {POLL_INTERVAL}s...")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="GPS Tsunami Detector — Live Pipeline"
    )
    parser.add_argument("--once", action="store_true",
                        help="Run one cycle and exit")
    args = parser.parse_args()
    main(once=args.once)
