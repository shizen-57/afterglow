# Afterglow, Alternative Design: "Overpass Control Room"

> An unconventional, spatial and playful UI/UX direction for the same product described in [design.md](design.md).
> It uses the same data, method and colour tokens. Only the way you *see* the record changes.
> Inspired by 3D logistics control dashboards (trucks arriving, docks loading, warehouses busy).
>
> **Rule note.** This is a written concept. Building it (3D scene, code, hi-fi visuals) happens only inside the hackathon window (from 13 Nov 2026 07:00 Dhaka). All numbers in sketches are **illustrative placeholders**.

---

## 1. The big idea

A warehouse control room is easy to understand because you can **watch the system work**:

- trucks arrive on a schedule;
- docks load or sit blocked;
- busy warehouses glow;
- a departure board tells you what is happening now and next.

The satellite fire record works exactly like that. We just never show it that way.

| Warehouse dashboard | Afterglow "Overpass" | Why it helps understanding |
|---|---|---|
| Trucks arriving on schedule | **Satellites passing over** at their real overpass times (Terra ~10:30, NOAA-20 ~12:40, S-NPP/Aqua ~13:30; NOAA-21 is offset from NOAA-20 within the same orbit, so verify its time from the FIRMS records) | People instantly see *why* sensors differ: different times, different "trucks" |
| Truck loading at a dock | **Satellite scanning** a district: a swath beam sweeps the terrain and sparks appear where it detects heat | Detections stop being abstract dots |
| Dock blocked by weather | **Clouds** float over cells and block the beam | "Not observed ≠ no fire" becomes obvious without one word |
| Busy warehouse glowing | **District columns** rise and glow by adjusted burning; colour = verdict vs normal | Where it's unusual, at a glance |
| Departures board | **Pass board**: which satellite passed, what it saw, what's next, which are retiring | Real operational info and the MODIS-retirement story in one panel |
| Fleet decommissioned | **"Ground the fleet"**: Terra, Aqua and S-NPP drop out of the sky | The central scientific claim becomes a visible event |

**Name:** *Overpass*. A satellite overpass is how the data is collected, and an overpass is also a bridge: our method bridges old satellites to new ones.

---

## 2. Concepts considered

Four out-of-the-box directions were explored. All share the same data and the same verdicts.

| Concept | What it looks like | Wow | Clarity | Scientific honesty risk | Build effort (26 h) | Verdict |
|---|---|---|---|---|---|---|
| **A. Overpass Control Room** | 3D terrain of the area; districts as glowing columns; satellites sweep overhead; clouds drift; departure-style pass board | Very high | High (mirrors the logistics dashboards people already know) | Medium: 3D heights can mislead (mitigated in §7) | Medium-high | **Lead** |
| **B. Time Ridge** | The 2D calendar *lifts* into a 3D landscape: x = season, depth = year, height = activity. Fire seasons become mountain ridges; cloud gaps become fog. | High | Medium-high (seasonality reads as terrain) | Medium | Medium | **Signature transition** inside A |
| **C. Fire Rings** | Each district is a tree cross-section: rings = years, angle = time of year, bright scars = unusual burning, gaps = not observed. A "forest" of districts side by side. | High (a nod to tree-ring fire-scar science) | Medium (radial angles are harder to read exactly) | Low-medium | Medium | **Extension:** district comparison |
| **D. Evidence Conveyor** | A conveyor/Sankey for one period: satellite passes → ground seen → lost to clouds → excluded (kilns, industry) → detections → adjusted value → verdict | Medium | Very high for "how did you get this number?" | Low | Low | **Inside the inspector** |

**Decision:** build **A** as the main view, with **B** as a one-click transition and **D** as the evidence panel. Keep design.md's 2D calendar as the **precision mode**: one toggle switches between *Sky* (Overpass) and *Grid* (calendar), sharing the same selection. Judges get the wow; analysts get exact numbers.

---

## 3. Main screen: the control room

### 3.1 Desktop layout (1440 × 900)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ ▣ Afterglow · OVERPASS   RANGAMATI ▾   2025 ▸ 6–13 MAR   ◉ SKY ○ GRID   ⌕ Ctrl K   ?   ◐            │
├───────────────────────────────────────────────────────────────────────┬──────────────────────────────┤
│                                                                       │ PASS BOARD        6 MAR 2025 │
│        ·  ─ ─ ─ ─ ─ ●NOAA-20 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  sky rail        │ SAT     TIME  SEEN  DET STATUS│
│                  ╲ swath beam                                         │ TERRA  10:31  58%    9  ◐ RETIRING│
│        ☁☁☁       ╲▒▒▒▒▒                                               │ NOAA21 12:38  66%  128  ● ACTIVE  │
│      ☁☁☁☁☁   ▲    ╲▒▒▒▒   ▌                                           │ NOAA20 12:47  66%  131  ● ACTIVE  │
│   (clouds:    ▌▌  ▲ ▌✦✦▌ ▌▌   ← district columns over 3D terrain      │ S-NPP  13:29  64%  112  ◐ ENDS 1 NOV │
│    no view)  ▌▌▌ ▌▌▌█▌▌▌▌▌▌      height = adjusted burning            │ AQUA   13:52  61%   14  ◐ RETIRING│
│             ▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔▔     colour = verdict vs normal           │ ─────────────────────────── │
│     Kaptai Lake ░░░░       glass cap = uncertainty range              │ HOT LIST · unusual now       │
│                                                                       │ 1 Rangamati   ▲ unusual  0.94 │
│  [camera: ⌂ Overview  ⤓ Top-down  ↻ Orbit  ⊕ Fit]                    │ 2 Bandarban   ▲ unusual  0.88 │
│                                                                       │ 3 Khagrachari ◆ possibly 0.71 │
├───────────────────────────────────────────────────────────────────────┴──────────────────────────────┤
│ VERDICT  6–13 Mar 2025: burning in Rangamati was UNUSUALLY HIGH vs 2003–22 (confidence high).        │
│ 2003 ────────────────────────────── 2012 ─────────── 2020 ──── 2024 ── 2026 ▮   ◀◀  ▶ PLAY SEASON  ▶▶   │ ← time scrubber
│      Terra·Aqua            + S-NPP         + NOAA-20  + NOAA-21   ⚠ fleet change   [ GROUND THE FLEET ] │
└──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Three zones, no cards:**

1. **The scene**, about 65% of the screen. Terrain, columns, clouds, satellites and beams.
2. **The pass board**, a right rail styled like an airport departures board. It shows what each satellite did on the selected day, followed by the "hot list" of districts.
3. **The time deck**, at the bottom. It holds the verdict sentence, a 2003–2026 scrubber with fleet milestones printed on it, the play control and the *Ground the fleet* button.

### 3.2 Scene composition (layers, bottom → top)

| Layer | Data | Look |
|---|---|---|
| Terrain | NASADEM (NASA) elevation, hillshaded; 1.5× vertical exaggeration so the Chittagong Hill Tracts' hill slopes show (jhum burns on slopes) | Matte, desaturated deep blue-grey; rivers and lakes darker |
| District floor plates | Admin units | Thin outline; selected district = Neon Yellow edge |
| Burning columns | Adjusted activity per district for the selected 8-day period (log-scaled) | Square columns; **solid part = lower bound of range**, **glass part = up to upper bound**; colour = verdict class |
| Detections | FIRMS points for the period | Small sparks: ■ MODIS (violet), ● VIIRS (aqua); excluded static sources = grey ◇ "chimneys" that don't glow |
| Clouds | Daily L3 fire mask class "cloud" aggregated over the period | Soft white translucent slabs over cells with < 30% clear view; the column underneath becomes a **dashed wireframe** |
| Sky rail | Satellite passes on the selected day | An arc high above the scene; each satellite is a small labelled glyph |
| Swath beam | During playback: each pass sweeps a translucent band across the area | Beam **breaks** where it hits cloud slabs; sparks pop where it finds fire |

**Honesty label (always visible, bottom-left of scene, DM Mono 11):** `Pass times from FIRMS records · orbit paths illustrative · heights log-scaled`.

### 3.3 Camera

- **Overview** (default): pitch 50°, bearing −20°, framed on the area. Pitch is capped at 60° so columns can't hide each other badly.
- **Top-down**: pitch 0°; columns become flat coloured tiles. This is the honest comparison view, one keypress away (`T`).
- **Orbit**: slow 360° auto-rotate, used only for the pitch video; it stops on any input.
- **Fit** recentres on the area. Mouse: drag rotates, right-drag pans, scroll zooms. Keyboard: arrows pan, `[` `]` rotate, `+` `−` zoom.

---

## 4. The pass board (departures-board style)

The pass board is useful, not decoration:

```
PASS BOARD · RANGAMATI · THU 6 MAR 2025          (times Asia/Dhaka · all values illustrative)
SATELLITE   PASS    GROUND SEEN   DETECTIONS   → AQUA-EQ.   STATUS
TERRA       10:31   58% ▮▮▮▮▮▯     9           11 [7–16]    ◐ DATA ENDS JAN 2027
NOAA-21     12:38   66% ▮▮▮▮▮▮▯   128          42 [30–58]   ● ACTIVE
NOAA-20     12:47   66% ▮▮▮▮▮▮▯   131          44 [31–60]   ● ACTIVE
S-NPP       13:29   64% ▮▮▮▮▮▮▯   112          38 [27–52]   ◐ DELIVERY ENDS 1 NOV 2026
AQUA        13:52   61% ▮▮▮▮▮▮▯    14          reference    ◐ DATA ENDS ~SEP 2027
────────────────────────────────────────────────────────────────────────────
NEXT LOOK (live mode)  NOAA-21 in 0 h 47 m · NOAA-20 in 1 h 37 m        [?]
```

- **Split-flap animation** when the day changes: characters flip in 120 ms. Under reduced motion they change instantly.
- **Status lights** use colour plus a symbol: ● active, ◐ retiring (with the date), ○ retired, plus a text label. Retiring is the storytelling hook: judges see the end dates every time they look.
- **Ground seen** is the per-satellite clear-view %, the same number as design.md's Coverage lens.
- **Next look** (extension, live mode only) predicts the next pass over the area with satellite.js and public CelesTrak orbital elements. That is real operational value for responders: when will I get the next satellite image?
- Clicking a row isolates that satellite in the scene: only its sparks and beam show, and the columns re-render from that satellite's estimate. This is a per-sensor comparison with no extra chart.

### Hot list

Districts ranked by Pr(unusual) for the selected period, each with a 46-cell micro-strip of its year:

```
HOT LIST · 6–13 MAR 2025
1  Rangamati    ▲ UNUSUAL   0.94   ░▒▓██▓▒░·········////
2  Bandarban    ▲ UNUSUAL   0.88   ░▒▓█▓▒░··········////
3  Khagrachari  ◆ POSSIBLY  0.71   ░▒▓▓▒░···········///
… (only districts with enough clear views; others listed as "not judged — clouds")
```

Hovering a row lifts that district's column and outlines it. Clicking flies the camera there in 600 ms.

---

## 5. The time deck (scrubber + playback)

```
VERDICT  6–13 Mar 2025: burning in Rangamati was UNUSUALLY HIGH vs 2003–22 (confidence high).
2003 ───────────────[2012 S-NPP joins]──────[2020 NOAA-20]──[2024 NOAA-21]──▮2026  ⚠ late 2026–27: 3 satellites stop
 ◀◀ year   ◀ period   ▶ PLAY SEASON   period ▶   year ▶▶     speed 1× 2× 4×     [ GROUND THE FLEET ]
```

- **Play season** steps through the 46 periods of the selected year at about 0.6 s each.
  - Columns rise and fall and clouds drift in and out.
  - In Bangladesh, the **monsoon cloud wall** rolls in around June and blankets the scene. The "not observed" problem becomes something you feel, not something you read.
  - In the dry season, the jhum peak lights up the hill districts.
- **Fleet milestones are printed on the scrubber**, so dragging across 2012 or 2020 makes new satellites *appear* in the sky rail.
- Dragging through years in **Raw** mode makes columns jump when satellites join. In **Adjusted** mode they don't. This is the 2012 / 2020 story, shown in motion.

---

## 6. Signature moment: "Ground the fleet"

1. The user presses **Ground the fleet** (preset: as planned for late 2027).
2. Terra, Aqua and S-NPP **dim, lose altitude and fade off the sky rail** (900 ms). Their pass-board rows flip to `○ OFF — SIMULATED`.
3. **Raw mode:** columns drop sharply, because fewer satellites means fewer detections. The hot list reshuffles and the verdicts flip.
4. **Adjusted mode:** columns barely move, but their **glass caps grow taller**. The uncertainty widens because fewer satellites are watching. Verdict colours mostly hold.
5. A counter slides into the time deck:
   `Held-out 2023–26 · Rangamati · verdicts kept: Raw 38% · Adjusted 91%   (illustrative)`
6. A one-line explanation: *"MODIS stops in 2027. Afterglow's answers mostly hold; where they don't, the glass cap shows the extra uncertainty."*
7. **Re-launch** brings the fleet back.

This is the 3D version of design.md §9. It is the same computation, and the same rule applies: only held-out years are tested, and earlier years are dimmed as "used for calibration".

---

## 7. Keeping 3D honest

3D is fun but can lie. These rules are non-negotiable:

| Risk | Rule |
|---|---|
| Perspective makes near columns look bigger | Colour carries the verdict, never height alone. A floating **reference column** shows height ticks (1, 10, 100). The Top-down view is one key away. |
| Occlusion (tall columns hide short ones) | Pitch is capped at 60°. Hovering a district makes columns in front go 30% translucent. The hot list lists everything in order. |
| Log scale misread as linear | The legend shows explicit log ticks. The tooltip always gives the exact number and range. |
| Animated beams and sparks imply exact orbit tracks | The label "orbit paths illustrative" is always on. Pass *times* are real (from FIRMS acquisition times); paths are stylized. |
| Clouds drawn wrong | Cloud slabs come only from the L3 fire-mask cloud class for that period. No decorative clouds ever. |
| Wow hides the evidence | Every visual element is clickable into the Evidence Conveyor (§8) and the precise Grid view. |

---

## 8. Evidence Conveyor (inspector)

Clicking a column or district opens the conveyor panel over the right rail. It is a horizontal flow (a Sankey with straight bands) that answers *"how did you get this number?"* visually:

```
6–13 MAR 2025 · RANGAMATI                                              ✕
PASSES        GROUND SEEN          KEPT                  DETECTIONS          RESULT
TERRA  ═══╗   ███████████▒▒▒▒▒     ████████████          ■■ 9      ─┐
AQUA   ═══╬═▶ seen 61–66%          minus 23 kilns/        ■■■ 14    ─┤      41 [29–55]
S-NPP  ═══╣   ☁ lost to cloud      industry, 6 low-conf   ●●●●● 112 ─┼──▶  UNUSUALLY HIGH
NOAA20 ═══╣   34–39%               (grey, can re-include) ●●●●● 131 ─┤      Pr 0.94
NOAA21 ═══╝                                               ●●●●● 128 ─┘      vs median 12
                 ▲ band width = area                       ▲ each satellite → bridge → Aqua scale
[ Open in NASA Worldview ↗ ]  [ See the ground (GIBS) ]  [ Grid view ]  [ CSV ]  [ Evidence sheet ]
```

- **Band thickness** = area or counts. The cloud loss is a band that visibly *falls off* the conveyor. Excluded static sources peel off into a grey side-chute.
- Hovering a satellite band highlights that satellite's sparks in the scene.
- This replaces the per-satellite table from design.md with something you can understand in 3 seconds. The table remains one click away (`Show as table`).

---

## 9. Time Ridge (signature transition)

From the Grid view (the 2D calendar of design.md), press **Lift** or `L`:

```
Grid (2D)                         Time Ridge (3D)
2026 ░▒▓██▓▒░ ////                     ▲▲          ← 2026 ridge
2025 ░▒▓███▓▒ ////          lift →    ▲███▲         ← 2025 taller = unusual year
 …                         (800 ms)  ▲▲▲▲▲▲  ☁☁ fog = not observed
2003 ░▒▓▓▒░  ////                   ▲▲▲▲   ☁☁
     J F M A M J J A S O N D            season → (x) · years ↗ (depth)
```

- x = 46 periods, depth = years (2003 at the back, current year at the front), height = adjusted activity. The fire season becomes a **mountain range running through time**: unusual years stand out as taller ridges, early seasons shift left, and monsoon gaps become fog banks.
- Click a ridge peak to select that period (same selection model).
- Ground the fleet works here too: the front ridges tremble but hold, and their glass tops grow.

---

## 10. Fire Rings (extension: compare districts)

A "forest" view for comparing many districts at once:

```
   Rangamati        Bandarban        Khagrachari       Cox's Bazar
     ◎                ◎                 ◎                  ◎
 rings = years (centre 2003 → edge 2026) · angle = time of year (Jan at top, clockwise)
 bright scar = unusual burning · gap = not observed (cloud) · ring thickness = confidence
```

- This is a nod to **dendrochronology**, where fire scientists read fire history from scars in tree rings, so the metaphor fits the subject.
- Radial angles are hard to read precisely. The rings are therefore for **pattern spotting only**. Hovering any ring segment shows the exact value, and clicking opens the Grid or Sky view at that period.

---

## 11. Feature integration map

Everything from design.md maps into this layout without adding containers.

| Feature (design.md id) | Where it lives in Overpass |
|---|---|
| F1 Verdict sentence | Time deck, first line |
| F2 Calendar | **Grid** toggle (precision mode) and the Time Ridge |
| F3 Lenses | Scene colour modes: Verdict / Activity / Coverage (clouds emphasised, columns greyed) / Satellites (sparks by sensor only) / Raw |
| F4 Not observed | Cloud slabs + dashed wireframe columns + "not judged" in the hot list |
| F5 Period evidence | Evidence Conveyor |
| F6 Stress test | **Ground the fleet** |
| F7 Area picker | Area menu + click a district + hot list |
| F9 Season profile and critical window | Play season, with the critical window shaded on the scrubber; profile mini-chart in Grid view |
| F10 Annual rank | Time Ridge heights + rank in tooltips |
| F13 Guidance | Flight tour (§12) + glossary + live legend |
| F14 Worldview / GIBS | Conveyor buttons; optional GIBS true-colour draped on the terrain for the selected date |
| F15 Static sources | Grey "chimney" glyphs that never glow; side-chute in the conveyor |
| F17 Command palette | Same (Ctrl K) |
| F22 Bangla | Same toggle; pass-board headers translated |
| **New:** Pass board | Right rail; per-satellite times, seen %, detections, status, retirement dates |
| **New:** Next look | Live-mode satellite pass prediction (extension) |
| **New:** Hot list | Right rail; districts ranked by Pr(unusual), excluding cloud-blocked ones |
| **New:** Monsoon wall replay | Play season, a teaching moment |

---

## 12. Guidance: the "flight tour"

A first-run camera tour of 5 stops, about 45 s, skippable. The camera moves; text cards are small and anchored.

1. **Fly in** from the Bay of Bengal to the area: *"Each column is a district. Taller and brighter means more burning than usual."*
2. **A satellite sweeps:** *"Five satellites pass over every day at different times. Each sees fire differently."*
3. **Clouds roll in:** *"Clouds block the view. Under a cloud we say 'not observed', never 'no fire'."*
4. **Glass cap:** *"Solid = what we're sure of. Glass = how far it might go."*
5. **Ground the fleet button glows:** *"In 2027 three of these satellites stop. Press this to see which answers survive."*

After the tour, the `?` key toggles labels on every scene element. The glossary works the same as in design.md.

---

## 13. Visual style

The colour tokens, fonts (Inter / Public Sans / DM Mono) and NASA-branding rules are identical to [design.md §2 and §15](design.md). Additions for 3D:

| Element | Spec |
|---|---|
| Scene background | Vertical gradient Space-900 → Deep Blue `#07173F` at the horizon. No stars, no planets. |
| Lighting | One directional "sun" from the south-east at 35° elevation + ambient 0.4. Columns get a soft top highlight only. |
| Columns | Opaque base (verdict colour), glass cap = same hue at 25% opacity with a 1 px top edge. Width 70% of the cell so the terrain shows between columns. |
| Sparks | 2–4 px point sprites with a 6 px bloom, **only during playback or hover**; static frames show plain glyphs so screenshots stay readable |
| Clouds | White at 55% opacity (dark theme) / Slate 40% (light theme), soft edges, slight drift during playback |
| Beam | Neon Blue `#0960E1` at 18% opacity, a 1 px bright leading edge |
| Pass board | DM Mono 13, uppercase headers, split-flap cells on a `--space-700` strip, status symbols + text |
| Motion | Purposeful only: playback, fleet grounding, camera fly-to. Everything stops under `prefers-reduced-motion`, and stepping replaces playing. |

---

## 14. Tech stack and performance

| Need | Choice | License |
|---|---|---|
| Map + 3D terrain | MapLibre GL JS (terrain from a raster DEM source) | BSD-3 |
| Columns, sparks, beams | deck.gl (`ColumnLayer`, `ScatterplotLayer`, `PathLayer`, `PolygonLayer`) interleaved with MapLibre | MIT |
| Terrain data | **NASADEM** (NASA, via LP DAAC), pre-rendered to terrain-RGB tiles for the demo areas, self-hosted for offline use | NASA open data |
| Satellite next-pass (extension) | satellite.js + CelesTrak GP orbital elements (Terra 25994, Aqua 27424, S-NPP 37849, NOAA-20 43013, NOAA-21 54234; verify IDs) | MIT / public data |
| Time Ridge | deck.gl `SimpleMeshLayer` or a three.js surface mesh (46 × 24 grid; tiny) | MIT |
| Conveyor | d3-sankey or a hand-drawn SVG (5 sources → 3 stages; very small) | ISC / own |

**Budgets:** 60 fps on a mid-range laptop at 1080p with up to 600 columns, 2,000 sparks and 200 cloud slabs. Scene JS ≤ 450 KB gzip, lazy-loaded *after* the verdict and pass board render. Terrain tiles for Bangladesh pre-cached.

**Fallback ladder** (decided automatically, also user-selectable):
1. Full 3D.
2. 3D without terrain (flat plates).
3. 2D map + Grid view (design.md).
4. Static screenshots + video.

If WebGL fails or the frame rate stays below 30 fps for 3 s, step down and show a toast: `Switched to 2D for smoother performance.`

---

## 15. Accessibility in a 3D world

- **The scene is never the only path.** Every fact in it lives in the DOM: pass board, hot list, verdict sentence, conveyor, Grid view (ARIA grid) and "Read as table".
- **Keyboard:** `Tab` cycles hot-list rows, `Enter` flies to that district and opens the conveyor. `T` = top-down, `G` = Grid view, `Space` = play/pause, `F` = ground the fleet.
- **Screen readers:** a live region announces state changes, e.g. *"Fleet grounded. Raw verdicts kept 38 percent, adjusted 91 percent."*
- `prefers-reduced-motion`: no playback autoplay, no split-flap flips, no camera fly-tos (instant cuts).
- **Colour + shape + text:** satellites have letters, verdicts have symbols (▲ ◆ ●), and clouds are also described in text.
- **Photosensitivity:** sparks never flash more than 3 times per second; bloom is subtle.

---

## 16. Risks and how this alternative could fail

| Risk | Mitigation |
|---|---|
| 3D eats the build time (26 h window) | Build order: verdict + pass board + hot list first (DOM, cheap), then flat 2D districts, then 3D columns, then clouds, then playback, then beams/sparks. Each step is demo-able. Time Ridge and Fire Rings are extensions only. |
| Judges see it as "just a pretty globe" | Lead with the pass board and the Ground-the-fleet counter; open the conveyor in every demo; show the Method page numbers. |
| Venue projector / laptop GPU too weak | The fallback ladder; record the demo video on the strongest laptop; test on the venue projector on Day 1. |
| Misleading 3D | §7 rules; Top-down and Grid are always one key away. |
| Motion sickness or distraction | Pitch cap, no auto-rotate except in the video, reduced-motion honoured. |

---

## 17. Build plan inside the hackathon (Overpass-specific)

| Order | Piece | Owner | Demo-able alone? | Est. |
|---|---|---|---|---|
| 1 | Verdict line + time deck scrubber (DOM) | FE | Yes | 1.5 h |
| 2 | Pass board + hot list (DOM, real data) | FE/UX | Yes, already a useful product | 2 h |
| 3 | MapLibre flat districts coloured by verdict | FE | Yes | 1.5 h |
| 4 | deck.gl columns with glass caps (range) | FE | Yes, the "wow" begins | 2 h |
| 5 | Cloud slabs from coverage + dashed columns | FE + SL | Yes | 1.5 h |
| 6 | Ground the fleet (shares the stress-test logic) | FE | Yes, the signature moment | 1.5 h |
| 7 | Evidence Conveyor | UX/FE | Yes | 2 h |
| 8 | Play season (period stepping, cloud drift) | FE | Yes | 1.5 h |
| 9 | Terrain (NASADEM tiles) | BE | Yes | 1.5 h |
| 10 | Beams + sparks during playback | FE | Polish | 2 h |
| 11 | Flight tour | UX | Polish | 1 h |
| Ext | Time Ridge · Fire Rings · Next look · GIBS drape | — | — | — |

If the team picks this direction, items 1–7 replace design.md build steps 1–6. The data pipeline and science are unchanged.

---

## 18. Pitch storyboard (30 s), Overpass version

```
0–5 s    Fly in over the Chittagong hills at dusk-blue; five satellites sweep the sky rail.
         Caption: "Five satellites record Earth's fires. Three stop by 2027."
5–11 s   Play season: the monsoon cloud wall rolls in, columns turn to dashed wireframes.
         Caption: "Clouds aren't calm. Afterglow shows what wasn't seen."
11–20 s  Press GROUND THE FLEET: Terra, Aqua, S-NPP fall away. Raw columns collapse;
         Afterglow columns hold, glass caps grow. Counter: verdicts kept Raw x% · Afterglow y%.
20–26 s  Click Rangamati → Evidence Conveyor → "UNUSUALLY HIGH, Pr 0.9x" → Worldview imagery.
26–30 s  Team names · "NASA FIRMS · MODIS & VIIRS fire masks · NASADEM" · URL.
         (All footage real data; "orbit paths illustrative" label visible.)
```

---

## 19. Which design should we build?

| | design.md (Instrument) | design_alternative.md (Overpass) |
|---|---|---|
| Analyst precision | Highest | High (via the Grid toggle) |
| First-impression wow | Good | Very high |
| Explains "not observed" and the fleet change | Clearly, in words and encodings | **Visibly, as events you watch** |
| Build risk in 26 h | Lower | Medium-high |
| Best for awards | Best Use of Science, Validity | Best Use of Data, Presentation, Most Inspirational, Local Impact |

**Recommendation:** build the **Overpass** shell (pass board + hot list + 2D/3D districts + Ground the fleet + conveyor) on top of design.md's tokens and data model. Keep the **Grid** calendar as the precision mode behind one key. Decide at **CP1 (12:30, Day 1):** if 3D columns aren't rendering real data by then, ship design.md's instrument as the main view and keep Overpass as the video and demo hero only.

---

## 20. Sources (checked 7 Oct 2026)

- Everything in [design.md §26](design.md#26-sources): NASA brand rules, HDS fonts and CC0 data-viz palette, Space Apps brand guide, judging rules.
- NASADEM elevation (NASA / LP DAAC): https://lpdaac.usgs.gov/products/nasadem_hgtv001/
- deck.gl (MIT): https://deck.gl · MapLibre GL JS (BSD-3): https://maplibre.org
- satellite.js (MIT): https://github.com/shashwatak/satellite-js · CelesTrak GP data: https://celestrak.org/NORAD/elements/
- FIRMS FAQ (overpass times; Terra ~10:30, Aqua/S-NPP ~13:30, NOAA-20 ~50 min before S-NPP; the NOAA-21 offset is described ambiguously, so read it from the acquisition times): https://www.earthdata.nasa.gov/data/tools/firms/faq
- Strategy and science basis: [docs/afterglow-plan.html](docs/afterglow-plan.html)
