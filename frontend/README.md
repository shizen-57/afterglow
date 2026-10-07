# Afterglow — Overpass

A working frontend based on `../design_alternative.md`, with real NASA FIRMS observations, a MapLibre geographic map, Bangladesh district boundaries, an interactive satellite board, 8-day calendar, evidence inspector, and fleet-removal simulation.

## Run

Requires Node.js 22.12 or newer.

```sh
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The server binds to localhost. Set `PORT` to use another port.

The interface uses React, official shadcn/ui components, Radix accessible primitives, Tailwind CSS, and Lucide icons. Public Sans and DM Mono are preserved. Map rendering, map colors, data layers, camera settings, and the map presentation follow the original version.

`npm run dev` runs the React development frontend and the data proxy together. For a production build, run `npm run build`, then `npm start`. The production server serves the compiled `dist` frontend with the same live data endpoints.

The included `data/latest.json` is a real NASA dataset fetched on 7 October 2026, not generated sample data. The UI shows the source and fetch timestamp in the evidence panel. Select **Refresh FIRMS** for current data. A server refresh reuses its cache for 15 minutes. NASA provides the last seven days; historical years require an archive CSV import.

```sh
npm run sync   # download current observations and boundaries
npm test       # parser, geography, time, filters, model validation, export
npm run build  # create a static distribution in dist/
```

The static build includes the latest saved dataset, map renderer, and boundary data. The live refresh endpoint requires the Node server; static hosting uses the saved record and local imports. Basemap tiles require internet access. If WebGL is unavailable, the calendar and evidence table remain usable.

## Working features

- Geographic MapLibre map with actual FIRMS points and district columns; pan, rotate, zoom, fit, top-down, orbit.
- District grouping uses point-in-polygon tests against Bangladesh ADM2 polygons, including holes and multipolygons.
- Pass board shows counts and earliest detection times converted from UTC to Asia/Dhaka. It does not claim to know undetected overpasses.
- Select a satellite to isolate its observations. Select a district in the map, list, menu, or command palette.
- 46-period calendar, year and period sliders, playback, and speed controls share the current selection.
- Grounding removes actual Terra, Aqua, and S-NPP records; re-launch restores them. Raw retention is computed from loaded detections.
- CSV, GeoJSON, and calibrated JSON imports are validated. The active dataset persists in IndexedDB.
- Evidence panel exposes provenance, filters, raw table, CSV export, evidence JSON, and a date-linked NASA Worldview launch.
- Dark/light themes, keyboard shortcuts, guided tour, screen-reader announcements, and reduced-motion support.
- shadcn/ui buttons, tabs, selects, sliders, tooltips, switches, cards, dialogs, an evidence sheet, command palette, export menu, tables, skeletons, and Sonner notifications.

## Import data

**FIRMS CSV:** required columns `latitude,longitude,acq_date,satellite`; supported optional columns `acq_time,confidence,frp,district,excluded`. Times are UTC HHMM. The parser supports Terra/T, Aqua/A, S-NPP/N, NOAA-20/N20/J1, and NOAA-21/N21/J2. Missing acquisition time is displayed as unknown; supply acquisition time for accurate pass-board times. Invalid CSV rows are counted and reported; identical source records are deduplicated. Unknown satellites are rejected. A CSV import replaces the active observation dataset and removes prior model estimates.

**District GeoJSON:** import a `.geojson` Polygon/MultiPolygon FeatureCollection. Name properties supported: `shapeName`, `name`, or `district`. These boundaries regroup the active observation records. Import a Bangladesh-only source when using the Bangladesh aggregate selector.

**Calibrated model JSON:** import the following structure. Numerical placeholders below specify the types; provide actual model outputs, not arbitrary values.

```text
{
  "version": 1,
  "provenance": "Your model, dataset version, calibration and method reference",
  "observations": [FIRMS records using the column names above],
  "districts": optional Polygon/MultiPolygon GeoJSON FeatureCollection,
  "estimates": [
    {
      "district": "exact district name, or Bangladesh for a national estimate",
      "year": integer,
      "period": integer from 0 to 45,
      "value": adjusted activity,
      "lower": lower uncertainty bound,
      "upper": upper uncertainty bound,
      "probability": Pr(unusual), from 0 to 1,
      "coverage": percent clear view, from 0 to 100,
      "baselineMedian": reference median,
      "grounded": optional {
        "value": grounded model estimate,
        "lower": grounded lower bound,
        "upper": grounded upper bound,
        "probability": grounded Pr(unusual)
      }
    }
  ]
}
```

Importing estimates enables Adjusted and Coverage lenses. They never estimate missing scientific fields. With a satellite isolated, calibrated aggregate estimates are unavailable; clear the satellite selection to read them. A grounded adjusted result requires its corresponding `grounded` record. The adjusted retention comparison uses supplied records in held-out years 2023–2026, with coverage ≥30%, comparing verdict classes before and after removal.

## Scientific boundaries

The frontend does not implement a MODIS/VIIRS harmonization model. Raw detections are not unique fires or comparable adjusted measurements. Absence of detections is not evidence of no fire. Coverage and cloud slabs cannot be inferred from active-fire CSVs. No clouds, confidence claims, retirement survival percentages, or historical results are invented.

NASADEM elevation, L3 fire-mask cloud slabs, historical calibration, true predicted next passes, Time Ridge, and Fire Rings are not included because their datasets or model outputs are absent. The core control room works on real observations now; the calibrated-output ingestion path supports the scientific frontend states.

## Sources

- [NASA FIRMS active fire data](https://firms.modaps.eosdis.nasa.gov/active_fire/): fixed public South Asia seven-day MODIS C6.1 and VIIRS C2 feeds (S-NPP, NOAA-20, NOAA-21). Data are filtered to Bangladesh polygons.
- [geoBoundaries](https://www.geoboundaries.org/): gbOpen Bangladesh ADM2. The saved GeoJSON records its source URL and attribution.
- [OpenFreeMap](https://openfreemap.org/): basemap; map attribution includes OpenStreetMap contributors.
- [MapLibre GL JS](https://maplibre.org/): geographic renderer, BSD-3-Clause.
- [shadcn/ui](https://ui.shadcn.com/): interface component source, MIT; [Lucide](https://lucide.dev/): consistent SVG icons, ISC.
- Public Sans and DM Mono: Google Fonts, with system fallbacks.

The Node server exposes only intended frontend files and fixed feed routes, with no arbitrary URL proxy. File imports stay in the browser.
