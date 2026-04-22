# Data Download Guide

All data is freely available. No cost.

## 1. NASA CDDIS — RINEX GPS Observations

Requires a free Earthdata account: https://earthdata.nasa.gov/

Base URL: `https://cddis.nasa.gov/archive/gps/data/daily/`

### Directory structure
```
/YYYY/DDD/YYo/   ← observation files (.YYo.Z)
/YYYY/DDD/YYn/   ← navigation files (.YYn.Z)
```
Where YYYY=year, DDD=day-of-year (001–366), YY=2-digit year.

### Station files by event

| Event | Year | DOY | Stations needed |
|-------|------|-----|-----------------|
| Tōhoku 2011 | 2011 | 070 | mkea, kokb, hnlc, guam |
| Chile 2010 | 2010 | 058 | mkea, kokb, hnlc, chat |
| Haida Gwaii 2012 | 2012 | 302 | mkea, kokb, hnlc, guam |
| Kuril 2006 | 2006 | 319 | mkea, kokb, hnlc, guam |
| Samoa 2009 | 2009 | 272 | mkea, kokb, hnlc |
| Kuril 2007 | 2007 | 013 | mkea, kokb, hnlc, guam |
| Peru 2001 | 2001 | 174+175 | mkea, kokb, hnlc, chat |
| Nicobar 2005 | 2005 | 087 | mkea, kokb, hnlc, guam |
| Sumatra 2004 | 2004 | 361 | mkea, kokb, guam |
| Tonga 2022 | 2022 | 015 | mkea, kokb, thti, thtg |

### Example filename
`mkea0700.11o.Z` = MKEA station, day 070, year 2011, observation file

### Save locations
Create folders on your Desktop:
```
rinex_tohoku_2011/
rinex_chile_2010/
rinex_haida_gwaii_2012/
rinex_kuril_2006/
rinex_samoa_2009/
rinex_kuril_2007/
rinex_peru_2001/
rinex_nicobar_2005/
rinex_sumatra_2004/
rinex_tonga_2022/
```

### Control days (11 quiet days)
See `scripts/control_day_batch.py` for the complete list of control day dates and station files.

---

## 2. Kp Geomagnetic Index

GFZ Potsdam — no account required:

```
https://kp.gfz.de/app/json/?start=YYYY-MM-DDT00:00:00Z&end=YYYY-MM-DDT23:59:00Z&index=Kp
```

Returns 8 3-hourly Kp values for the day. Maximum value used as daily Kp.

Already hardcoded in `scripts/detector_params.py` for all events.

---

## 3. NOAA Tide Gauge — Hilo Hawaii (station 1617760)

No account required:

```
https://api.tidesandcurrents.noaa.gov/api/prod/datagetter?product=water_level&application=web_services&begin_date=YYYYMMDD&end_date=YYYYMMDD&datum=MLLW&station=1617760&time_zone=GMT&units=metric&interval=6&format=json
```

Tsunami arrival identified by `"f":"0,0,1,0"` flag bits in the response.
Amplitude = (peak − trough) / 2 in the 2-hour post-arrival window.

---

## 4. Station Coordinates

| ID | Lat | Lon | Alt (m) | Location |
|----|-----|-----|---------|----------|
| mkea | 19.801°N | 155.456°W | 3763 | Mauna Kea, Hawaii |
| kokb | 22.127°N | 159.665°W | 1167 | Kokee Park, Kauai |
| hnlc | 21.297°N | 157.816°W | 5 | Honolulu |
| guam | 13.489°N | 144.868°E | 83 | Guam |
| chat | 43.956°S | 176.566°W | 63 | Chatham Islands, NZ |
| thti | 17.577°S | 149.606°W | 87 | Tahiti |
| thtg | 17.577°S | 149.606°W | 87 | Tahiti (2nd receiver) |
