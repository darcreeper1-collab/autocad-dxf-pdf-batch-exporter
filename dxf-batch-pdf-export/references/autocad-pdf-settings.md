# AutoCAD PDF Settings

Use AutoCAD for final plotting when SHX/text handling, colors, lineweights, linetypes, blocks, CTB/STB behavior, and page placement matter.

## Default plot choices

- COM ProgID: automatically discover the highest registered `AutoCAD.Application.*` unless `-AutoCadProgId` is specified.
- Device: `DWG To PDF.pc3`.
- Media: `ISO_full_bleed_A1_(841.00_x_594.00_MM)` for an A1 landscape frame.
- Plot type: window, centered, standard scale fit-to-paper, lineweights on, plot styles off by default.
- Temporary output: `.codexplot`, then rename to `.pdf` after `PlotToFile` completes.

## Instance behavior

The default workflow creates a dedicated hidden AutoCAD instance and disposes it in `finally`. It waits for AutoCAD idle state and retries only transient busy COM calls. `-ReuseExistingAutoCAD 1` is an explicit exception; the existing user application is not hidden or quit, and only the job's own opened document is closed.

## Useful variables

The plotter sets best-effort values for `BACKGROUNDPLOT=0`, `FILEDIA=0`, `CMDDIA=0`, `EXPERT=5`, `PDFSHX=0`, `EPDFSHX=0`, `PDFSHXTEXT=0`, `PUBLISHOPEN=0`, `PUBLISHVIEW=0`, `PLOTNOTIFY=0`, and `VIEWPLOTDETAILS=0` on the conversion document. A warning in `plot_results.json.layoutWarnings` means that the particular AutoCAD release rejected a setting; inspect the sample PDF rather than assuming fidelity.