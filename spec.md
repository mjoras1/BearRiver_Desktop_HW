# Bear River Gage Explorer

## Purpose

An interactive map for engineers, water managers, and other people exploring streamflow in the Bear River Basin (HUC 1601), which spans Utah, Idaho, and Wyoming and drains toward the Great Salt Lake. Users can find USGS stream gages, inspect recent readings, and review a year of daily flow.

## Platform

The primary platform is a Windows desktop application built with Python 3.9 or later and Tkinter. Internet access is required to retrieve live USGS and watershed data. Excel export requires the `openpyxl` package. The application is not designed as a mobile or browser-based interface.

## Inputs

The app has no user-entered numeric values. Its controls are:

- **Map navigation:** pan and zoom with mouse, touch, or the map's standard controls. A reset control returns to the full basin.
- **Gage selection:** select a marker on the map or a result in the gage list to show its details.
- **Historical gages:** a checkbox, off by default, that adds sites without a flow reading in the last seven days.

The selected gage's chart always covers the 365 days ending on the current date; users do not enter a date range. The app uses the USGS Water Data API and the WBD geometry for HUC 1601. It must not use `waterservices.usgs.gov`.

## Calculations

- Download the HUC 1601 boundary as GeoJSON from the USGS National Map WBD service, layer 2 (4-digit hydrologic units), querying `HUC4 = 1601` and requesting coordinates in EPSG:4326.
- Request USGS stream monitoring locations from the USGS Water Data OGC API (`monitoring-locations`, `agency_code=USGS`, `site_type_code=ST`) within the boundary's bounding box. Follow every pagination link, then keep only site points inside the HUC 1601 polygon.
- Request the latest continuous streamflow records from the USGS Water Data OGC API (`latest-continuous`, parameter code `00060`, instantaneous statistic `00011`, USGS stream sites) within the same bounding box. Follow every pagination link and use the latest valid, non-missing record for each site.
- A site is **current** when it has a non-missing discharge reading timestamped within the previous seven days. The cutoff is evaluated using timestamps in UTC. A reading of 0 cfs is valid. Sites not meeting this rule are historical and are hidden until the historical-gages checkbox is selected.
- For a selected site, show its drainage area from the monitoring-location record in square miles, and its latest available non-missing discharge reading and timestamp. Convert `m^3/s` readings to `cfs` by multiplying by 35.3146667; `ft^3/s` readings are already in `cfs`. Do not label an unsupported unit as `cfs`. Show the API's data qualifier and approval status when provided. If any value is unavailable, say so rather than displaying zero.
- Link each selected site to its official USGS monitoring-location page using its site number.
- Request daily values from the USGS Water Data OGC API `daily` collection for the selected monitoring-location ID, parameter code `00060`, and daily mean statistic ID `00003`. Query 365 consecutive calendar dates, inclusive, ending on today's date in `America/Denver`.
- Plot daily mean discharge (`cfs`) against those dates. Convert supported units to `cfs`; keep missing dates as gaps and do not interpolate or replace them with zero.
- Compute the displayed mean daily flow over the chart window as
  `mean flow (cfs) = sum of available daily mean flows (cfs) / number of available daily values`.
  Exclude missing days from both the sum and count, and show the number of daily values used. Do not round values before calculating; display flow to one decimal place.
- Convert API timestamps to Mountain Time (`America/Denver`) for display, while using the original timestamp to determine whether a site is current. Display drainage area in square miles (`mi^2`) and flow in cubic feet per second (`cfs`).

## Outputs

- A Leaflet map with a visible HUC 1601 basin boundary, current gage markers, a legend, and a count of the displayed sites. Historical sites use a visually distinct marker style when enabled.
- A gage list with each site's name and site number. Selecting a site from either the list or map highlights it and opens its details.
- A selected-gage details panel showing name, site number, drainage area (`mi^2`), most recent flow (`cfs`), reading time (Mountain Time), data qualifier and approval status when available, and a link to that site's official USGS page.
- A labeled hydrograph of daily mean flow (`cfs`) for the past 365 days, with dates on the x-axis and flow on the y-axis. Missing days appear as gaps.
- The mean daily flow for the chart window and the number of daily values used to calculate it.
- Clear loading, no-data, and error messages. If a data service fails, explain what could not be loaded rather than presenting an empty map as a successful result.
- Attribution and links to the USGS Water Data API and the Watershed Boundary Dataset.

## Look and feel

Use a clean, professional river-and-forest visual theme with restrained green and blue accents, readable contrast, and clear labels and units. On a wide screen, place the map beside a gage list and details panel. On a phone, stack the list and details below the map, keep controls usable by touch, and avoid horizontal scrolling. The initial view shows the entire basin, current gages, a short explanation, and the historical-gages checkbox. Provide loading and error states that remain readable on both screen sizes.

## Validation

### Handwritten calculations

| Validation | Handwritten inputs and calculation | Expected result | Verification |
|---|---|---|---|
| 1 | Daily means of 12 cfs, one missing day, 18 cfs, and 30 cfs: `(12 + 18 + 30) / 3` | Mean `20.0 cfs`; 3 values used; missing day remains a gap | Pass: arithmetic independently checked and `summarize_daily_series` test returns mean 20.0, count 3, and 1 missing day. |
| 2 | The second handwritten validation supplied was the same calculation and inputs as Validation 1: `(12 + 18 + 30) / 3` | Mean `20.0 cfs`; 3 values used; missing day remains a gap | Same result; duplicate of Validation 1, so it is not an independent test case. |

### Tkinter layout proportions

The desktop app is configured for a 1500 × 900 initial window and a minimum size of 1100 × 700. The table records source-level proportion checks separately from visual checks.

| Layout check | Specified proportion or measurement | Result |
|---|---|---|
| Initial desktop window | 1500 × 900 px | Pass: configured in `app.py`. |
| Minimum resizable window | 1100 × 700 px | Pass: configured in `app.py`. |
| Map and side-panel columns | Grid weights 3:2 (60% / 40% of the space after the 12 px gap); approximately 864 px / 576 px at 1500 px window width after 24 px outer margins | Pass: the grid weight allocation is proportional. |
| Station list and details rows | Grid weights 1:2 (approximately 33% / 67% of the available side-column height) | Pass: the grid weight allocation is proportional. |
| Basin map drawing | Uses one shared coordinate scale for longitude and latitude | Pass: map geometry preserves its aspect ratio instead of stretching to fill the canvas. |
| Hydrograph width | Plot x-coordinates scale to the chart canvas width | Pass: plot width follows the resizable canvas. |
| Rendered fit and clipping at 1500 × 900 | Inspect the live window for clipped labels, overlapping panels, and usable controls | Not verified: the app window did not remain available for visual inspection in this run. Do not treat source-level ratios as visual sign-off. |

**Live-data validation:** Compare the most recent flow and drainage area shown for three selected gages with their official USGS pages. For one of those gages, download the daily mean flows for the chart window and independently calculate their arithmetic mean, excluding missing days. Record the three site numbers, observation times, source values, and hand-computed mean in `02_validation` before claiming the live-data validation passes. This validation remains pending; no source observations or results are recorded yet.

## Out of scope

- Gages outside HUC 1601.
- Forecasting streamflow, issuing flood warnings, or recommending operational decisions.
- Editing or correcting USGS observations.
- Interpolating missing readings or estimating values that the APIs do not provide.
- Using the retiring `waterservices.usgs.gov` service.

## Features

Add these only after the required app behavior passes validation:

1. **Gage search and filtering:** let users find sites by name or site number and filter the list to current or historical sites. Selecting a result also selects it on the map. This helps users locate a particular station in a basin with hundreds of sites.
2. **Hydrograph CSV export:** let users download the selected gage's chart-window daily mean values, dates, units, and site number as a CSV. Missing days remain blank so the exported data cannot be mistaken for zero flow.

## Build stages

1. **Responsive mockup:** Create the single-file page layout with a placeholder basin map, gage list, historical-gages control, selected-gage details, sample hydrograph, mean-flow summary, and clear sample/loading/error states. Use illustrative values only; do not connect live services or implement flow calculations. Check desktop and phone layouts and make sure selecting a sample gage and showing/hiding sample historical gages demonstrates the intended interface.
2. **Live basin and gage map:** Load the HUC 1601 boundary and all matching USGS streamflow sites, handle paginated results, classify current and historical sites using the seven-day rule, and show markers and the historical-gages toggle. Check basin coverage, marker locations, site counts, toggle behavior, and service error states.
3. **Selected-gage details:** Connect map markers and the gage list to the selected-gage panel. Show the site's name, number, drainage area, latest non-missing flow, timestamp, qualifier when provided, and official USGS link. Check valid, zero, stale, and missing readings against source pages.
4. **Hydrograph and validation:** Load the selected site's daily mean flows from the `daily` collection for 365 consecutive Mountain-time calendar dates, show gaps for missing days, calculate the mean and valid-day count, and complete the hand calculation and live-data comparisons. Record source values and results in `02_validation`; fix discrepancies before marking validation complete.

After the required app passes validation, implement each item in **Features** as its own change, check it, and commit it separately.

## New Features

1. **Saving and opening work:** Save the selected site number, search text, and historical-gage setting in a `.brwork.json` file. Opening a work file restores these settings and refreshes live data from USGS; it does not store an offline copy of observations.
2. **Exporting results:** Export the selected gage's chart-window daily values, dates, units, and site number as CSV or Excel (`.xlsx`). Missing daily values remain blank in both formats.