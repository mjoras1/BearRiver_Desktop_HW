# Bear River Gage Explorer

A Tkinter desktop application for exploring USGS stream gages in the Bear River Basin (HUC 1601). It retrieves the basin boundary and gage data from the USGS services described in [spec.md](spec.md).

## Requirements

- Python 3.9 or later
- Tkinter (included with most standard Python installations)
- Dependencies listed in `requirements.txt`
- Internet access for the USGS Water Data API and USGS National Map services

Install the Excel export dependency:

```powershell
py -m pip install -r requirements.txt
```

On Windows, if the application cannot find the `America/Denver` time zone database, install the `tzdata` package:

```powershell
py -m pip install tzdata
```

## Run

From this project folder, run:

```powershell
py app.py
```

On systems where the Python launcher is unavailable, use:

```text
python app.py
```

The application loads live basin and gage data when it starts. Select a gage from the list or map to load its details and daily hydrograph. Enable **Historical** to include gages without a recent reading.

- **Save Work** saves a `.brwork.json` file with the selected gage, search text, and historical-gage setting. **Open Work** restores those settings and refreshes the gage data from USGS; saved files do not contain offline copies of the observations.
- **Export** offers CSV and Excel (`.xlsx`) formats for the selected gage's 365-day daily-flow series. Missing values remain blank in both formats.

Run the focused feature tests with:

```powershell
py -m unittest -v test_app.py
```

The existing `index.html` is the earlier browser-based version. Run `app.py` to use the Tkinter desktop application.
