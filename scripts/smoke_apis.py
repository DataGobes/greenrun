"""Check that the two free data sources answer. Run: python scripts/smoke_apis.py"""

import json
import sys
import urllib.request
from datetime import date, timedelta

DAY = (date.today() - timedelta(days=2)).isoformat()
NEXT = (date.today() - timedelta(days=1)).isoformat()
CHECKS = {
    "Energy-Charts /price": f"https://api.energy-charts.info/price?bzn=DE-LU&start={DAY}&end={NEXT}",
    "Energy-Charts /public_power": f"https://api.energy-charts.info/public_power?country=de&start={DAY}&end={NEXT}",
    "Open-Meteo forecast": (
        "https://api.open-meteo.com/v1/forecast?latitude=51.17&longitude=10.45"
        f"&hourly=temperature_2m,shortwave_radiation,wind_speed_100m&start_date={DAY}&end_date={DAY}&timezone=UTC"
    ),
}


def main() -> int:
    failed = 0
    for name, url in CHECKS.items():
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                body = json.load(response)
            print(f"ok    {name}: keys {sorted(body)[:6]}")
        except Exception as error:  # noqa: BLE001 - report every source, then fail
            failed += 1
            print(f"FAIL  {name}: {error}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
