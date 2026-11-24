import csv
import json
import threading
import tkinter as tk
import tkinter.messagebox as messagebox
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
from tkinter import filedialog, ttk


USGS_API = "https://api.waterdata.usgs.gov/ogcapi/v1"
WBD_QUERY = "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/2/query"
RECENCY_WINDOW = timedelta(days=7)
MOUNTAIN = ZoneInfo("America/Denver")
WORK_FILE_VERSION = 1
DAILY_EXPORT_HEADERS = ("date", "site_number", "daily_mean_cfs", "unit")


def create_work_file(selected_site_number, search_text, show_historical):
    return {
        "version": WORK_FILE_VERSION,
        "selected_site_number": selected_site_number,
        "search_text": search_text,
        "show_historical": show_historical,
    }


def validate_work_file(data):
    if (not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data["version"] != WORK_FILE_VERSION):
        raise ValueError("This is not a supported Bear River work file.")
    site_number = data.get("selected_site_number")
    search_text = data.get("search_text")
    show_historical = data.get("show_historical")
    if (site_number is not None and not isinstance(site_number, str)
            or not isinstance(search_text, str)
            or type(show_historical) is not bool):
        raise ValueError("The work file contains invalid or incomplete settings.")
    return create_work_file(site_number, search_text, show_historical)


def export_rows(site_number, daily_series):
    rows = [DAILY_EXPORT_HEADERS]
    for day in daily_series:
        value = day["value"]
        rows.append((
            day["date"],
            site_number,
            "" if value is None else f"{value:.10g}",
            "cfs",
        ))
    return rows


def write_daily_csv(path, site_number, daily_series):
    with open(path, "w", newline="", encoding="utf-8") as output:
        csv.writer(output).writerows(export_rows(site_number, daily_series))


def write_daily_excel(path, site_number, daily_series):
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Daily Mean Flow"
    sheet.append(DAILY_EXPORT_HEADERS)
    for day in daily_series:
        sheet.append((
            day["date"],
            site_number,
            day["value"],
            "cfs",
        ))
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for column, width in (("A", 14), ("B", 18), ("C", 20), ("D", 10)):
        sheet.column_dimensions[column].width = width
    workbook.save(path)


def summarize_daily_series(series):
    values = [day["value"] for day in series if day["value"] is not None]
    return {
        "mean": sum(values) / len(values) if values else None,
        "count": len(values),
        "missing": len(series) - len(values),
    }


class BearRiverApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Bear River Gage Explorer")
        self.geometry("1500x900")
        self.minsize(1100, 700)
        self.configure(bg="#f3f5f0")

        self.boundary_features = []
        self.sites = []
        self.sites_by_id = {}
        self.selected_id = None
        self.daily_series = []
        self.map_bounds = None
        self.map_points = []
        self.data_loading = True
        self.pending_work_file = None

        self._configure_styles()
        self._build_ui()
        threading.Thread(target=self.load_data, daemon=True).start()

    def _configure_styles(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background="#f3f5f0", foreground="#20342f",
                        font=("Segoe UI", 10))
        style.configure("Card.TFrame", background="#ffffff")
        style.configure("Heading.TLabel", background="#ffffff",
                        foreground="#20342f", font=("Segoe UI", 12, "bold"))
        style.configure("Subheading.TLabel", background="#ffffff",
                        foreground="#6e7c75", font=("Segoe UI", 9))
        style.configure("Status.TLabel", background="#e6efe9",
                        foreground="#173b32", font=("Segoe UI", 10))
        style.configure("Error.TLabel", background="#f7dfdc",
                        foreground="#8b3028", font=("Segoe UI", 10))
        style.configure("Toggle.TCheckbutton", background="#ffffff",
                        foreground="#20342f")

    def _build_ui(self):
        header = tk.Frame(self, bg="#173b32", height=64)
        header.pack(fill="x")
        header.pack_propagate(False)
        tk.Label(header, text="~", bg="#173b32", fg="#dbe8df",
                 font=("Segoe UI", 20, "bold"), width=3).pack(side="left", padx=(18, 4), pady=12)
        tk.Label(header, text="Bear River Basin", bg="#173b32", fg="#ffffff",
                 font=("Segoe UI", 12, "bold")).pack(side="left")
        tk.Label(header, text="Water data explorer / Utah, Idaho, Wyoming",
                 bg="#173b32", fg="#b9c9c1", font=("Segoe UI", 9)).pack(
                     side="right", padx=24)

        body = tk.Frame(self, bg="#f3f5f0")
        body.pack(fill="both", expand=True, padx=24, pady=(18, 12))

        title_row = tk.Frame(body, bg="#f3f5f0")
        title_row.pack(fill="x")
        title_copy = tk.Frame(title_row, bg="#f3f5f0")
        title_copy.pack(side="left", fill="x", expand=True)
        tk.Label(title_copy, text="Bear River Gage Explorer", bg="#f3f5f0",
                 fg="#20342f", font=("Segoe UI", 22, "bold")).pack(anchor="w")
        tk.Label(title_copy,
                 text="Explore stream gages across the Bear River Basin and inspect recent conditions.",
                 bg="#f3f5f0", fg="#6e7c75", font=("Segoe UI", 10)).pack(
                     anchor="w", pady=(2, 10))
        work_controls = tk.Frame(title_row, bg="#f3f5f0")
        work_controls.pack(side="right", padx=(12, 0), pady=(2, 12))
        tk.Button(work_controls, text="Open Work", command=self.open_work_file,
                  relief="solid", bd=1, bg="#ffffff", fg="#20342f",
                  padx=10, pady=5).pack(side="left", padx=(0, 6))
        tk.Button(work_controls, text="Save Work", command=self.save_work_file,
                  relief="solid", bd=1, bg="#e6efe9", fg="#173b32",
                  padx=10, pady=5).pack(side="left")

        self.status_var = tk.StringVar(
            value="Loading live basin boundary and USGS stream gages...")
        self.status_label = ttk.Label(body, textvariable=self.status_var,
                                      style="Status.TLabel", anchor="w",
                                      padding=(10, 7))
        self.status_label.pack(fill="x", pady=(0, 10))

        dashboard = tk.Frame(body, bg="#f3f5f0")
        dashboard.pack(fill="both", expand=True)
        self.dashboard_frame = dashboard
        dashboard.columnconfigure(0, weight=3)
        dashboard.columnconfigure(1, weight=2)
        dashboard.rowconfigure(0, weight=1)

        left = ttk.Frame(dashboard, style="Card.TFrame")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        right = ttk.Frame(dashboard, style="Card.TFrame")
        right.grid(row=0, column=1, sticky="nsew")

        map_heading = tk.Frame(left, bg="#ffffff")
        map_heading.pack(fill="x", padx=16, pady=(14, 8))
        tk.Label(map_heading, text="Basin gage map", bg="#ffffff",
                 fg="#20342f", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.map_count_var = tk.StringVar(value="Loading sites...")
        tk.Label(map_heading, textvariable=self.map_count_var, bg="#edf3ef",
                 fg="#486157", font=("Segoe UI", 9), padx=8, pady=4).pack(side="right")

        self.map_canvas = tk.Canvas(left, bg="#eef3eb", highlightthickness=1,
                                    highlightbackground="#dde5dd")
        self.map_canvas.pack(fill="both", expand=True, padx=16, pady=(0, 8))
        self.map_canvas.bind("<Configure>", lambda _e: self.render_map())
        self.map_canvas.bind("<Button-1>", self.on_map_click)

        legend = tk.Frame(left, bg="#ffffff")
        legend.pack(fill="x", padx=16, pady=(0, 12))
        self._legend_item(legend, "#28684d", "Current gage")
        self._legend_item(legend, "#7d8c83", "Historical gage")
        tk.Canvas(legend, width=28, height=12, bg="#ffffff", highlightthickness=0).pack(
            side="left", padx=(12, 2))
        tk.Frame(legend, width=20, height=2, bg="#527a59").place(
            in_=legend, x=legend.winfo_reqwidth() + 132, y=6)
        tk.Label(legend, text="HUC 1601 boundary", bg="#ffffff",
                 fg="#6e7c75", font=("Segoe UI", 9)).pack(side="left", padx=(4, 0))

        right.grid_rowconfigure(0, weight=1)
        right.grid_rowconfigure(1, weight=2)
        right.grid_columnconfigure(0, weight=1)

        stations = ttk.Frame(right, style="Card.TFrame")
        stations.grid(row=0, column=0, sticky="nsew", padx=12, pady=(12, 6))
        station_head = tk.Frame(stations, bg="#ffffff")
        station_head.pack(fill="x", padx=10, pady=(8, 6))
        tk.Label(station_head, text="USGS stream gages", bg="#ffffff",
                 fg="#20342f", font=("Segoe UI", 12, "bold")).pack(side="left")
        self.station_count_var = tk.StringVar(value="Loading locations...")
        tk.Label(station_head, textvariable=self.station_count_var, bg="#ffffff",
                 fg="#6e7c75", font=("Segoe UI", 9)).pack(side="right")

        controls = tk.Frame(stations, bg="#ffffff")
        controls.pack(fill="x", padx=10)
        self.search_var = tk.StringVar()
        search = tk.Entry(controls, textvariable=self.search_var,
                          relief="solid", bd=1, fg="#20342f", bg="#ffffff")
        search.pack(side="left", fill="x", expand=True, padx=(0, 8), ipady=4)
        search.insert(0, "Search name or site number")
        search.bind("<FocusIn>", lambda _e: search.delete(0, "end")
                    if search.get().startswith("Search ") else None)
        search.bind("<KeyRelease>", lambda _e: self.render_station_list())
        self.historical_var = tk.BooleanVar(value=False)
        tk.Checkbutton(controls, text="Historical", variable=self.historical_var,
                       command=self.on_historical_toggle, bg="#ffffff",
                       activebackground="#ffffff", selectcolor="#ffffff",
                       fg="#20342f").pack(side="right")

        list_frame = tk.Frame(stations, bg="#ffffff")
        list_frame.pack(fill="both", expand=True, padx=10, pady=(6, 10))
        self.station_list = tk.Listbox(list_frame, height=7, activestyle="none",
                                       relief="flat", highlightthickness=1,
                                       highlightbackground="#e2e8e2",
                                       selectbackground="#dceadf",
                                       selectforeground="#20342f",
                                       bg="#ffffff", fg="#20342f",
                                       font=("Segoe UI", 9))
        scrollbar = ttk.Scrollbar(list_frame, orient="vertical",
                                  command=self.station_list.yview)
        self.station_list.configure(yscrollcommand=scrollbar.set)
        self.station_list.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        self.station_list.bind("<<ListboxSelect>>", self.on_station_select)

        details = ttk.Frame(right, style="Card.TFrame")
        details.grid(row=1, column=0, sticky="nsew", padx=12, pady=(6, 12))
        detail_head = tk.Frame(details, bg="#ffffff")
        detail_head.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(detail_head, text="Selected gage", bg="#ffffff",
                 fg="#20342f", font=("Segoe UI", 12, "bold")).pack(side="left")

        self.site_name_var = tk.StringVar(value="No gage selected")
        self.site_number_var = tk.StringVar(value="Select a marker or list item")
        self.site_status_var = tk.StringVar(value="Select a gage")
        name_row = tk.Frame(details, bg="#ffffff")
        name_row.pack(fill="x", padx=14)
        tk.Label(name_row, textvariable=self.site_name_var, bg="#ffffff",
                 fg="#20342f", font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(name_row, textvariable=self.site_status_var, bg="#edf3ef",
                 fg="#486157", font=("Segoe UI", 8), padx=6, pady=3).pack(
                     side="right")
        tk.Label(details, textvariable=self.site_number_var, bg="#ffffff",
                 fg="#6e7c75", font=("Segoe UI", 9)).pack(anchor="w", padx=14)

        metrics = tk.Frame(details, bg="#ffffff")
        metrics.pack(fill="x", padx=14, pady=8)
        for column in range(2):
            metrics.columnconfigure(column, weight=1)
        self.flow_var = tk.StringVar(value="Unavailable")
        self.area_var = tk.StringVar(value="Unavailable")
        self._metric(metrics, 0, "Most recent flow", self.flow_var)
        self._metric(metrics, 1, "Drainage area", self.area_var)

        meta = tk.Frame(details, bg="#ffffff")
        meta.pack(fill="x", padx=14)
        self.reading_var = tk.StringVar(value="Select a gage")
        self.qualifier_var = tk.StringVar(value="Select a gage")
        self.approval_var = tk.StringVar(value="Select a gage")
        self._meta_row(meta, "Reading time", self.reading_var)
        self._meta_row(meta, "Data qualifier", self.qualifier_var)
        self._meta_row(meta, "Approval status", self.approval_var)

        link_row = tk.Frame(details, bg="#ffffff")
        link_row.pack(fill="x", padx=14, pady=(4, 6))
        self.link_button = tk.Button(link_row, text="Open USGS monitoring page",
                                     command=self.open_usgs_page, relief="flat",
                                     cursor="hand2", bg="#ffffff", fg="#2f6f60",
                                     activebackground="#ffffff",
                                     disabledforeground="#6e7c75",
                                     font=("Segoe UI", 9, "underline"))
        self.link_button.pack(anchor="w")
        self.link_button.configure(state="disabled")

        chart_head = tk.Frame(details, bg="#ffffff")
        chart_head.pack(fill="x", padx=14)
        tk.Label(chart_head, text="Daily mean discharge (cfs)", bg="#ffffff",
                 fg="#20342f", font=("Segoe UI", 10, "bold")).pack(side="left")
        self.chart_range_var = tk.StringVar(value="Select a gage")
        tk.Label(chart_head, textvariable=self.chart_range_var, bg="#ffffff",
                 fg="#6e7c75", font=("Segoe UI", 8)).pack(side="right")

        self.chart_canvas = tk.Canvas(details, bg="#ffffff", height=170,
                                      highlightthickness=0)
        self.chart_canvas.pack(fill="x", padx=14, pady=(4, 2))
        self.chart_canvas.bind("<Configure>", lambda _e: self.render_chart())

        summary = tk.Frame(details, bg="#ffffff")
        summary.pack(fill="x", padx=14, pady=(2, 10))
        self.mean_var = tk.StringVar(value="Unavailable")
        tk.Label(summary, text="Mean daily flow", bg="#ffffff",
                 fg="#6e7c75", font=("Segoe UI", 8)).pack(side="left")
        tk.Label(summary, textvariable=self.mean_var, bg="#ffffff",
                 fg="#20342f", font=("Segoe UI", 13, "bold")).pack(side="left", padx=(8, 4))
        tk.Label(summary, text="cfs", bg="#ffffff", fg="#6e7c75",
                 font=("Segoe UI", 8)).pack(side="left")
        self.count_var = tk.StringVar(value="Select a gage")
        tk.Label(summary, textvariable=self.count_var, bg="#ffffff",
                 fg="#6e7c75", font=("Segoe UI", 8)).pack(side="right")
        self.export_button = tk.Menubutton(
            summary, text="Export", relief="solid", bd=1,
            bg="#f7f9f6", fg="#20342f", padx=8, pady=2)
        export_menu = tk.Menu(self.export_button, tearoff=False)
        export_menu.add_command(
            label="CSV (.csv)", command=lambda: self.export_data("csv"))
        export_menu.add_command(
            label="Excel (.xlsx)", command=lambda: self.export_data("xlsx"))
        self.export_button.configure(menu=export_menu)
        self.export_button.pack(side="right", padx=(8, 0))
        self.export_button.configure(state="disabled")

        footer = tk.Frame(body, bg="#f3f5f0")
        footer.pack(fill="x", pady=(8, 0))
        tk.Label(footer,
                 text="Data: USGS Water Data API  |  WBD: USGS National Map",
                 bg="#f3f5f0", fg="#6e7c75", font=("Segoe UI", 8)).pack(anchor="w")

    def _legend_item(self, parent, color, text):
        canvas = tk.Canvas(parent, width=14, height=14, bg="#ffffff",
                           highlightthickness=0)
        canvas.pack(side="left")
        canvas.create_oval(2, 2, 12, 12, fill=color, outline="#ffffff")
        tk.Label(parent, text=text, bg="#ffffff", fg="#6e7c75",
                 font=("Segoe UI", 9)).pack(side="left", padx=(2, 10))

    def _metric(self, parent, column, label, value_var):
        frame = tk.Frame(parent, bg="#f7f9f6", highlightthickness=1,
                         highlightbackground="#e2e8e2")
        frame.grid(row=0, column=column, sticky="nsew", padx=(0, 6 if column == 0 else 0),
                   pady=2, ipadx=8, ipady=6)
        tk.Label(frame, text=label, bg="#f7f9f6", fg="#6e7c75",
                 font=("Segoe UI", 8)).pack(anchor="w")
        tk.Label(frame, textvariable=value_var, bg="#f7f9f6",
                 fg="#20342f", font=("Segoe UI", 14, "bold")).pack(anchor="w")

    def _meta_row(self, parent, label, value_var):
        frame = tk.Frame(parent, bg="#ffffff")
        frame.pack(fill="x", pady=2)
        tk.Label(frame, text=label, bg="#ffffff", fg="#6e7c75",
                 width=16, anchor="w", font=("Segoe UI", 8)).pack(side="left")
        tk.Label(frame, textvariable=value_var, bg="#ffffff", fg="#20342f",
                 anchor="e", font=("Segoe UI", 8)).pack(side="right", fill="x", expand=True)

    def request_json(self, url, label):
        request = urllib.request.Request(url, headers={"Accept": "application/json",
                                                       "User-Agent": "BearRiverGageExplorer/1.0"})
        with urllib.request.urlopen(request, timeout=45) as response:
            if response.status != 200:
                raise RuntimeError(f"{label} request failed (HTTP {response.status}).")
            data = json.loads(response.read().decode("utf-8"))
        if data.get("error"):
            raise RuntimeError(f"{label} service error: {data['error'].get('message', 'unknown')}.")
        return data

    def request_all_features(self, first_url, label):
        features = []
        visited = set()
        next_url = first_url
        origin = urllib.parse.urlparse(USGS_API).origin
        while next_url:
            parsed = urllib.parse.urlparse(next_url)
            if len(visited) >= 100:
                raise RuntimeError(f"{label} pagination exceeded 100 pages.")
            if parsed.scheme + "://" + parsed.netloc != origin:
                raise RuntimeError(f"{label} returned an unexpected pagination link.")
            if next_url in visited:
                raise RuntimeError(f"{label} returned a repeated pagination link.")
            visited.add(next_url)
            page = self.request_json(next_url, label)
            page_features = page.get("features")
            if not isinstance(page_features, list):
                raise RuntimeError(f"{label} response did not contain a feature list.")
            features.extend(page_features)
            next_link = next((link for link in page.get("links", [])
                              if link.get("rel") == "next"), None)
            next_url = urllib.parse.urljoin(next_url, next_link["href"]) if next_link else None
        return features

    def load_data(self):
        try:
            self.after(0, lambda: self.set_status(
                "Loading the HUC 1601 boundary and USGS stream gages...", False))
            params = urllib.parse.urlencode({
                "where": "HUC4='1601'",
                "outFields": "HUC4,NAME",
                "returnGeometry": "true",
                "outSR": "4326",
                "f": "geojson",
            })
            boundary = self.request_json(WBD_QUERY + "?" + params,
                                         "USGS Watershed Boundary Dataset")
            features = boundary.get("features", [])
            if not features:
                raise RuntimeError("The WBD service returned no HUC 1601 boundary.")
            self.boundary_features = [feature["geometry"] for feature in features
                                      if feature.get("geometry")]

            coordinates = []
            self.collect_coordinates(self.boundary_features, coordinates)
            if not coordinates:
                raise RuntimeError("The WBD response did not contain usable basin coordinates.")
            bounds = [min(p[0] for p in coordinates),
                      min(p[1] for p in coordinates),
                      max(p[0] for p in coordinates),
                      max(p[1] for p in coordinates)]
            self.map_bounds = bounds

            location_url = self.make_url(
                "/collections/monitoring-locations/items",
                {"f": "json", "limit": "1000", "agency_code": "USGS",
                 "site_type_code": "ST", "bbox": ",".join(map(str, bounds))})
            flow_url = self.make_url(
                "/collections/latest-continuous/items",
                {"f": "json", "limit": "1000", "agency_code": "USGS",
                 "site_type_code": "ST", "parameter_code": "00060",
                 "statistic_id": "00011", "bbox": ",".join(map(str, bounds))})
            location_features = self.request_all_features(
                location_url, "USGS monitoring locations")
            flow_features = self.request_all_features(
                flow_url, "USGS latest streamflow")
            latest = self.create_latest_flow_index(flow_features)
            self.normalize_sites(location_features, latest)
            self.after(0, self.finish_load)
        except Exception as exc:
            self.after(0, lambda error=exc: self.show_load_error(error))

    def make_url(self, path, params):
        return USGS_API + path + "?" + urllib.parse.urlencode(params)

    def collect_coordinates(self, value, coordinates):
        if isinstance(value, list):
            if len(value) >= 2 and isinstance(value[0], (int, float)):
                coordinates.append(value)
            else:
                for part in value:
                    self.collect_coordinates(part, coordinates)
        elif isinstance(value, dict):
            self.collect_coordinates(value.get("coordinates"), coordinates)

    def create_latest_flow_index(self, features):
        latest = {}
        now = datetime.now(timezone.utc)
        for feature in features:
            props = feature.get("properties", {})
            site_id = props.get("monitoring_location_id")
            raw = props.get("value")
            if not site_id or raw in (None, ""):
                continue
            try:
                value = float(raw)
                timestamp = datetime.fromisoformat(
                    str(props["time"]).replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                continue
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            timestamp = timestamp.astimezone(timezone.utc)
            previous = latest.get(site_id)
            if not previous or timestamp > previous["timestamp"]:
                latest[site_id] = {
                    "timestamp": timestamp,
                    "value": value,
                    "unit": props.get("unit_of_measure"),
                    "qualifier": props.get("qualifier"),
                    "approval_status": props.get("approval_status"),
                }
        return latest

    def point_on_segment(self, point, start, end):
        cross = (point[1] - start[1]) * (end[0] - start[0]) - (
            point[0] - start[0]) * (end[1] - start[1])
        if abs(cross) > 1e-10:
            return False
        return (min(start[0], end[0]) - 1e-10 <= point[0] <= max(start[0], end[0]) + 1e-10
                and min(start[1], end[1]) - 1e-10 <= point[1] <= max(start[1], end[1]) + 1e-10)

    def point_in_ring(self, point, ring):
        inside = False
        for index, start in enumerate(ring):
            end = ring[index - 1]
            if self.point_on_segment(point, start, end):
                return True
            if (start[1] > point[1]) != (end[1] > point[1]):
                intersection_x = (end[0] - start[0]) * (point[1] - start[1]) / (
                    end[1] - start[1]) + start[0]
                if point[0] < intersection_x:
                    inside = not inside
        return inside

    def point_in_polygon(self, point, polygon):
        if not polygon or not self.point_in_ring(point, polygon[0]):
            return False
        return not any(self.point_in_ring(point, ring) for ring in polygon[1:])

    def point_in_geometry(self, point, geometry):
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates", [])
        if geometry_type == "Polygon":
            return self.point_in_polygon(point, coordinates)
        if geometry_type == "MultiPolygon":
            return any(self.point_in_polygon(point, polygon)
                       for polygon in coordinates)
        return False

    def normalize_sites(self, location_features, latest):
        now = datetime.now(timezone.utc)
        unique = {}
        for feature in location_features:
            props = feature.get("properties", {})
            coordinates = feature.get("geometry", {}).get("coordinates")
            if not isinstance(coordinates, list) or len(coordinates) < 2:
                continue
            point = [float(coordinates[0]), float(coordinates[1])]
            if not any(self.point_in_geometry(point, geometry)
                       for geometry in self.boundary_features):
                continue
            site_number = props.get("monitoring_location_number")
            site_id = props.get("id") or ("USGS-" + str(site_number) if site_number else "")
            if not site_id or site_id in unique:
                continue
            flow = latest.get(site_id)
            is_current = bool(flow and now - flow["timestamp"] <= RECENCY_WINDOW
                              and flow["timestamp"] <= now)
            area = props.get("drainage_area")
            try:
                area = float(area) if area not in (None, "") else None
            except (TypeError, ValueError):
                area = None
            unique[site_id] = {
                "id": site_id,
                "number": site_number or site_id.replace("USGS-", ""),
                "name": props.get("monitoring_location_name") or
                        "Unnamed USGS stream site",
                "latitude": point[1],
                "longitude": point[0],
                "drainage_area": area,
                "latest": flow,
                "current": is_current,
            }
        self.sites = sorted(unique.values(),
                            key=lambda site: (site["name"], site["number"]))
        self.sites_by_id = {site["id"]: site for site in self.sites}

    def set_status(self, message, error=False):
        self.status_var.set(message)
        self.status_label.configure(style="Error.TLabel" if error else "Status.TLabel")

    def show_load_error(self, exc):
        self.data_loading = False
        self.set_status(
            "Live basin and gage data could not be loaded. " + str(exc), True)
        self.station_count_var.set("Gage data unavailable")
        self.map_count_var.set("Unavailable")
        self.map_canvas.delete("all")
        self.map_canvas.create_text(
            self.map_canvas.winfo_width() // 2,
            self.map_canvas.winfo_height() // 2,
            text="Could not load live basin data.\nCheck your connection and reopen the app.",
            fill="#8b3028", font=("Segoe UI", 11), justify="center")
        if self.pending_work_file is not None:
            self.pending_work_file = None
            messagebox.showwarning(
                "Could not restore saved work",
                "Live USGS data failed to load, so the saved gage selection "
                "could not be restored.",
                parent=self)

    def finish_load(self):
        self.data_loading = False
        if not self.sites:
            self.set_status(
                "The HUC 1601 boundary loaded, but no USGS stream sites were found inside it.",
                True)
        else:
            self.set_status("", False)
            self.status_label.pack_forget()
        self.render_map()
        self.render_station_list()
        if self.pending_work_file is not None:
            self.apply_work_file(self.pending_work_file)
            self.pending_work_file = None

    def visible_sites(self):
        query = self.search_var.get().strip().lower()
        if query == "search name or site number":
            query = ""
        return [site for site in self.sites
                if (self.historical_var.get() or site["current"])
                and (not query or query in site["name"].lower()
                     or query in str(site["number"]).lower())]

    def render_station_list(self):
        if not hasattr(self, "station_list"):
            return
        visible = self.visible_sites()
        self.station_list.delete(0, "end")
        self.station_list._visible_ids = [site["id"] for site in visible]
        for site in visible:
            status = "Current" if site["current"] else "Historical"
            self.station_list.insert(
                "end", f"{site['name']}  |  USGS {site['number']}  |  {status}")
        current = sum(1 for site in self.sites if site["current"])
        self.station_count_var.set(
            f"Showing {len(visible)} of {len(self.sites)} sites / "
            f"{current} current")
        self.map_count_var.set(
            f"{len(visible)} shown / {current} current")
        self.render_map()

    def on_historical_toggle(self):
        if not self.historical_var.get() and self.selected_id:
            site = self.sites_by_id.get(self.selected_id)
            if site and not site["current"]:
                self.selected_id = None
                self.clear_details()
        self.render_station_list()

    def on_station_select(self, _event):
        selection = self.station_list.curselection()
        if not selection:
            return
        site_id = self.station_list._visible_ids[selection[0]]
        self.select_site(site_id)

    def on_map_click(self, event):
        best = None
        best_distance = 14
        for site_id, (longitude, latitude) in getattr(self, "map_points", []):
            canvas_x = longitude
            canvas_y = latitude
            distance = ((event.x - canvas_x) ** 2 +
                        (event.y - canvas_y) ** 2) ** 0.5
            if distance <= best_distance:
                best_distance = distance
                best = site_id
        if best:
            self.select_site(best)

    def select_site(self, site_id):
        site = self.sites_by_id.get(site_id)
        if not site:
            return
        if not site["current"] and not self.historical_var.get():
            self.historical_var.set(True)
            self.render_station_list()
        self.selected_id = site_id
        self.update_details(site)
        self.render_map()
        threading.Thread(target=self.load_daily_chart,
                         args=(site,), daemon=True).start()

    def update_details(self, site):
        self.site_name_var.set(site["name"])
        self.site_number_var.set(f"Site number {site['number']}")
        self.site_status_var.set(
            "Current / last 7 days" if site["current"] else "Historical")
        latest = site["latest"]
        if not latest:
            self.flow_var.set("Unavailable")
            self.reading_var.set("No discharge reading available")
            self.qualifier_var.set("Not reported")
            self.approval_var.set("Not reported")
        else:
            flow = self.convert_flow(latest["value"], latest["unit"])
            self.flow_var.set(f"{flow:.1f}" if flow is not None else "Unavailable")
            timestamp = latest["timestamp"].astimezone(MOUNTAIN)
            self.reading_var.set(timestamp.strftime("%b %-d, %Y, %-I:%M %p MDT"))
            self.qualifier_var.set(latest["qualifier"] or "None reported")
            self.approval_var.set(latest["approval_status"] or "Not reported")
        self.area_var.set(
            f"{site['drainage_area']:,.2f}" if site["drainage_area"] is not None
            else "Unavailable")
        self.link_button.configure(state="normal")
        self.chart_range_var.set("Loading...")
        self.mean_var.set("Unavailable")
        self.count_var.set("Loading...")
        self.export_button.configure(state="disabled")
        self.chart_canvas.delete("all")
        self.chart_canvas.create_text(
            self.chart_canvas.winfo_width() // 2,
            70, text="Loading daily mean discharge...",
            fill="#6e7c75", font=("Segoe UI", 10))

    def clear_details(self):
        self.site_name_var.set("No gage selected")
        self.site_number_var.set("Select a marker or list item")
        self.site_status_var.set("Select a gage")
        self.flow_var.set("Unavailable")
        self.area_var.set("Unavailable")
        self.reading_var.set("Select a gage")
        self.qualifier_var.set("Select a gage")
        self.approval_var.set("Select a gage")
        self.link_button.configure(state="disabled")
        self.chart_range_var.set("Select a gage")
        self.mean_var.set("Unavailable")
        self.count_var.set("Select a gage")
        self.daily_series = []
        self.render_chart()

    def convert_flow(self, value, unit):
        normalized = str(unit or "").replace(" ", "").lower()
        if normalized in ("ft^3/s", "ft3/s", "ft³/s", "cfs",
                          "cubicfeetpersecond"):
            return value
        if normalized in ("m^3/s", "m3/s", "m³/s", "cms", "cumecs",
                          "cubicmeterspersecond"):
            return value * 35.3146667
        return None

    def load_daily_chart(self, site):
        try:
            end = datetime.now(MOUNTAIN).date()
            start = end - timedelta(days=364)
            start_text = start.isoformat()
            end_text = end.isoformat()
            url = self.make_url(
                "/collections/daily/items",
                {"f": "json", "limit": "1000",
                 "monitoring_location_id": site["id"],
                 "parameter_code": "00060", "statistic_id": "00003",
                 "time": start_text + "/" + end_text})
            features = self.request_all_features(
                url, "USGS daily mean streamflow")
            values = {}
            for feature in features:
                props = feature.get("properties", {})
                date_text = str(props.get("time") or "")[:10]
                if date_text < start_text or date_text > end_text:
                    continue
                raw = props.get("value")
                value = None if raw in (None, "") else float(raw)
                if value is not None:
                    value = self.convert_flow(value, props.get("unit_of_measure"))
                    if value is None:
                        raise RuntimeError(
                            "The daily flow record uses an unsupported unit.")
                try:
                    modified = datetime.fromisoformat(
                        str(props.get("last_modified", "")).replace("Z", "+00:00"))
                    modified_key = modified.timestamp()
                except (TypeError, ValueError):
                    modified_key = 0
                previous = values.get(date_text)
                if not previous or modified_key >= previous[1]:
                    values[date_text] = (value, modified_key)
            series = []
            for offset in range(365):
                date = start + timedelta(days=offset)
                record = values.get(date.isoformat())
                series.append({"date": date.isoformat(),
                               "value": record[0] if record else None})
            if self.selected_id == site["id"]:
                self.after(0, lambda: self.update_chart(
                    site, series, start_text, end_text))
        except Exception as exc:
            if self.selected_id == site["id"]:
                message = "Daily mean discharge could not be loaded. " + str(exc)
                self.after(0, lambda: self.show_chart_error(message))

    def update_chart(self, site, series, start_text, end_text):
        self.daily_series = series
        self.chart_range_var.set(
            f"{datetime.strptime(start_text, '%Y-%m-%d').strftime('%b %d, %Y')} - "
            f"{datetime.strptime(end_text, '%Y-%m-%d').strftime('%b %d, %Y')}")
        summary = summarize_daily_series(series)
        if summary["count"]:
            self.mean_var.set(f"{summary['mean']:.1f}")
            suffix = (f"; {summary['missing']} missing day"
                      f"{'s' if summary['missing'] != 1 else ''}"
                      if summary["missing"] else "")
            self.count_var.set(
                f"{summary['count']} daily values used{suffix}")
            self.export_button.configure(state="normal")
        else:
            self.mean_var.set("Unavailable")
            self.count_var.set("0 daily values used")
            self.chart_canvas.delete("all")
            self.chart_canvas.create_text(
                self.chart_canvas.winfo_width() // 2, 70,
                text="No daily mean discharge values are available for this gage.",
                fill="#6e7c75", font=("Segoe UI", 10))
        self.render_chart()

    def show_chart_error(self, message):
        self.chart_range_var.set("Unavailable")
        self.mean_var.set("Unavailable")
        self.count_var.set("Unavailable")
        self.chart_canvas.delete("all")
        self.chart_canvas.create_text(
            self.chart_canvas.winfo_width() // 2, 70, text=message,
            fill="#8b3028", font=("Segoe UI", 9), justify="center")

    def render_map(self):
        canvas = self.map_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 300)
        if not self.map_bounds:
            canvas.create_text(width // 2, height // 2,
                               text="Loading basin boundary...",
                               fill="#6e7c75", font=("Segoe UI", 11))
            return
        min_lon, min_lat, max_lon, max_lat = self.map_bounds
        pad = 28
        lon_span = max(max_lon - min_lon, 0.0001)
        lat_span = max(max_lat - min_lat, 0.0001)
        scale = min((width - 2 * pad) / lon_span,
                    (height - 2 * pad) / lat_span)

        def project(longitude, latitude):
            x = (width - lon_span * scale) / 2 + (longitude - min_lon) * scale
            y = (height - lat_span * scale) / 2 + (max_lat - latitude) * scale
            return x, y

        for geometry in self.boundary_features:
            polygons = []
            if geometry["type"] == "Polygon":
                polygons = [geometry["coordinates"]]
            elif geometry["type"] == "MultiPolygon":
                polygons = geometry["coordinates"]
            for polygon in polygons:
                for ring in polygon:
                    points = [coordinate for point in ring
                              for coordinate in project(point[0], point[1])]
                    canvas.create_polygon(points, fill="#dfe9dc",
                                          outline="#527a59", width=2,
                                          stipple="gray25")

        self.map_points = []
        for site in self.visible_sites():
            x, y = project(site["longitude"], site["latitude"])
            self.map_points.append((site["id"], (x, y)))
            selected = site["id"] == self.selected_id
            fill = "#bc8540" if selected else (
                "#28684d" if site["current"] else "#7d8c83")
            radius = 7 if selected else 5
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius,
                               fill=fill, outline="#ffffff", width=2)

    def render_chart(self):
        canvas = self.chart_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 300)
        height = max(canvas.winfo_height(), 150)
        if not self.daily_series:
            canvas.create_text(width // 2, height // 2,
                               text="Select a gage to load daily mean discharge.",
                               fill="#6e7c75", font=("Segoe UI", 9))
            return
        values = [day["value"] for day in self.daily_series
                  if day["value"] is not None]
        if not values:
            return
        left, right = 48, width - 12
        top, bottom = 12, height - 30
        observed_max = max(values)
        observed_min = min(values)
        axis_min = observed_min if observed_min < 0 else 0
        axis_max = observed_max
        if axis_max <= axis_min:
            axis_max = axis_min + 1

        def y_for(value):
            return bottom - (value - axis_min) / (axis_max - axis_min) * (
                bottom - top)

        for tick_index in range(5):
            value = axis_min + (axis_max - axis_min) * tick_index / 4
            y = y_for(value)
            canvas.create_line(left, y, right, y, fill="#edf1ec",
                               dash=(3, 4))
            canvas.create_text(left - 6, y, text=f"{value:.0f}",
                               fill="#8a958f", anchor="e",
                               font=("Segoe UI", 8))
        canvas.create_line(left, top, left, bottom, fill="#dfe6df")
        canvas.create_line(left, bottom, right, bottom, fill="#dfe6df")

        segment = []
        for index, day in enumerate(self.daily_series):
            x = left + index / (len(self.daily_series) - 1) * (right - left)
            if day["value"] is None:
                if len(segment) >= 2:
                    canvas.create_line(segment, fill="#3f8874", width=2,
                                       smooth=False)
                segment = []
            else:
                segment.extend((x, y_for(day["value"])))
        if len(segment) >= 2:
            canvas.create_line(segment, fill="#3f8874", width=2,
                               smooth=False)

        for index in (0, 182, 364):
            day = self.daily_series[index]
            x = left + index / 364 * (right - left)
            date = datetime.strptime(day["date"], "%Y-%m-%d")
            canvas.create_text(x, bottom + 14,
                               text=date.strftime("%b %d"),
                               fill="#8a958f",
                               font=("Segoe UI", 8),
                               anchor="middle")

    def open_usgs_page(self):
        if not self.selected_id:
            return
        site = self.sites_by_id.get(self.selected_id)
        if site:
            webbrowser.open(
                "https://waterdata.usgs.gov/monitoring-location/USGS-" +
                urllib.parse.quote(str(site["number"])) + "/")

    def export_data(self, file_format):
        if not self.selected_id or not self.daily_series:
            return
        site = self.sites_by_id[self.selected_id]
        extension = "." + file_format
        if file_format not in ("csv", "xlsx"):
            messagebox.showerror("Export failed", "Choose CSV or Excel.",
                                 parent=self)
            return
        path = filedialog.asksaveasfilename(
            defaultextension=extension,
            filetypes=[("CSV files", "*.csv")] if file_format == "csv"
            else [("Excel workbooks", "*.xlsx")],
            initialfile=f"USGS_{site['number']}_daily_mean{extension}")
        if not path:
            return
        if Path(path).suffix.lower() != extension:
            messagebox.showerror(
                "Export failed", f"Choose a {extension} file name.",
                parent=self)
            return
        try:
            if file_format == "csv":
                write_daily_csv(path, site["number"], self.daily_series)
            else:
                write_daily_excel(path, site["number"], self.daily_series)
        except (OSError, ValueError, ImportError) as exc:
            messagebox.showerror("Export failed", str(exc), parent=self)
            return
        messagebox.showinfo("Export complete", f"Saved results to:\n{path}",
                            parent=self)

    def save_work_file(self):
        selected_site = self.sites_by_id.get(self.selected_id)
        site_number = str(selected_site["number"]) if selected_site else None
        search_text = self.search_var.get().strip()
        if search_text == "Search name or site number":
            search_text = ""
        path = filedialog.asksaveasfilename(
            defaultextension=".brwork.json",
            filetypes=[("Bear River work files", "*.brwork.json"),
                       ("JSON files", "*.json")],
            initialfile="BearRiver-work.brwork.json")
        if not path:
            return
        payload = create_work_file(
            site_number, search_text, self.historical_var.get())
        try:
            Path(path).write_text(
                json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Save failed", str(exc), parent=self)
            return
        messagebox.showinfo(
            "Work saved",
            "Saved your search, historical-gage setting, and selected gage.\n"
            "Live USGS data will refresh when this file is opened.",
            parent=self)

    def open_work_file(self):
        path = filedialog.askopenfilename(
            filetypes=[("Bear River work files", "*.brwork.json"),
                       ("JSON files", "*.json")])
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            payload = validate_work_file(data)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            messagebox.showerror("Could not open work file", str(exc),
                                 parent=self)
            return
        if self.data_loading:
            self.pending_work_file = payload
            messagebox.showinfo(
                "Work file queued",
                "The saved view will be restored after live gage data finishes loading.",
                parent=self)
            return

        self.pending_work_file = payload
        self.data_loading = True
        self.status_var.set("Refreshing live basin and gage data...")
        self.status_label.configure(style="Status.TLabel")
        self.status_label.pack(fill="x", pady=(0, 10),
                               before=self.dashboard_frame)
        threading.Thread(target=self.load_data, daemon=True).start()

    def apply_work_file(self, payload):
        self.search_var.set(payload["search_text"])
        self.historical_var.set(payload["show_historical"])
        self.render_station_list()
        site_number = payload["selected_site_number"]
        if site_number is None:
            self.selected_id = None
            self.clear_details()
            self.render_map()
            return
        site = next((candidate for candidate in self.sites
                     if str(candidate["number"]) == site_number), None)
        if site is None:
            self.selected_id = None
            self.clear_details()
            self.render_map()
            messagebox.showwarning(
                "Gage not found",
                f"USGS site {site_number} is not in the live basin results. "
                "The saved search and historical setting were restored.",
                parent=self)
            return
        self.select_site(site["id"])


if __name__ == "__main__":
    app = BearRiverApp()
    app.mainloop()
