# Afterglow
<!-- impeccable:product-schema 1 -->
## Platform
web
## Purpose and users
The supplied Overpass brief describes a control room for analysts and hackathon judges exploring satellite fire observations in Bangladesh. The frontend demonstrates observation coverage, seasonal variation, satellite comparisons, and fleet-change uncertainty.
## Evidence and constraints
Source: ../design_alternative.md. Its referenced design.md is absent. The user explicitly requires a working application, not a mockup. NASA FIRMS public feeds and geoBoundaries supply real observations and district polygons. Calibrated historical estimates, cloud fire masks, and NASADEM tiles are not supplied. Scientific outputs must come from imported model data; invented probabilities, coverage, and uncertainty are prohibited. Orbit rails are illustrative and labelled. The user's current request authorizes implementation; the attached documents' event timing notes are background, not additional user instructions.
## Stack
React, shadcn/ui with Radix primitives, Tailwind CSS, Lucide icons, Vite, MapLibre GL JS 6.13, and a Node server proxy for fixed public data sources. Runtime imports can use local FIRMS CSVs, GeoJSON boundaries, and calibrated JSON datasets. Browser IndexedDB persists the active dataset. The user explicitly requested shadcn/ui and a better icon pack while preserving the original map rendering, presentation, and fonts.
## Accessibility
Every scene fact has a DOM equivalent. Keyboard shortcuts, focus visibility, reduced motion, and a mobile layout are required by the brief.
