# AutoCAD PDF Settings

Use AutoCAD plotting when fidelity matters: native SHX/text handling, colors, lineweights, linetypes, block visibility, and CTB/STB behavior are all more reliable than lightweight DXF renderers.

## Default plot choices

- COM ProgID: `AutoCAD.Application.25` unless the installed version requires another ProgID.
- Device: `DWG To PDF.pc3`.
- Media: `ISO_full_bleed_A1_(841.00_x_594.00_MM)` for A1 landscape PFD/P&ID sheets.
- Plot type: window.
- Scale: standard scale, fit to paper.
- Center plot: true.
- Plot rotation: `0` by default for 841 x 594 landscape frames; adjust only after a sample render proves the orientation is wrong.
- Plot with lineweights: true.
- Plot styles: off by default unless the project requires a CTB/STB mapping.

## Quiet conversion pattern

Use `PlotToFile` with an intermediate extension such as `.codexplot`, wait for the file, then rename it to `.pdf`. This prevents Windows from opening WPS or the default PDF viewer after every page. Keep `SuppressViewerWindows=1` as a fallback, but do not kill viewer processes.

## Useful AutoCAD variables

Set these best-effort before plotting: `BACKGROUNDPLOT=0`, `FILEDIA=0`, `CMDDIA=0`, `EXPERT=5`, `PDFSHX=0`, `EPDFSHX=0`, `PDFSHXTEXT=0`, `PUBLISHOPEN=0`, `PUBLISHVIEW=0`, `PLOTNOTIFY=0`, and `VIEWPLOTDETAILS=0`.
