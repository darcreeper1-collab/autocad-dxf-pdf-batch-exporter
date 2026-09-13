# AutoCAD PDF Settings

Use AutoCAD for final plotting when SHX/text handling, colors, lineweights, linetypes, blocks, CTB/STB behavior, and page placement matter.

## Default plot choices

- COM ProgID: automatically discover the highest registered `AutoCAD.Application.*` unless `-AutoCadProgId` is specified.
- Device: `DWG To PDF.pc3`.
- Media: `ISO_full_bleed_A1_(841.00_x_594.00_MM)` for an A1 landscape frame.
- Plot type: window, centered, standard scale fit-to-paper, lineweights on, plot styles off by default.
- Temporary output: `.codexplot`, then rename to `.pdf` after `PlotToFile` completes.

## Instance behavior

The default workflow creates a dedicated AutoCAD instance, records its window identity before hiding it, and attempts cleanup in `finally`. It waits for idle state and retries transient busy COM calls. A supervised worker bounds non-returning calls with `-ComCallTimeoutSeconds` (default 300); on timeout only that worker is stopped and the identified owned AutoCAD window is requested visible. AutoCAD is not killed, and forced termination cannot guarantee cleanup. `-ReuseExistingAutoCAD 1` is explicit; that application is never hidden or quit. See troubleshooting for residual instances and activation-time limits.

Device, canonical media, paper units, window plot type, centering, fit scale, rotation, plot-style/color and lineweight controls are required properties. Assignment and readback must succeed, and critical values are checked again before each plot. Device refresh also fails fast. Unsupported optional settings still produce warnings. Inspect `autoCad.cleanupFailed` and COM events before claiming a clean shutdown.

## Useful variables

The plotter sets best-effort values for `BACKGROUNDPLOT=0`, `FILEDIA=0`, `CMDDIA=0`, `EXPERT=5`, `PDFSHX=0`, `EPDFSHX=0`, `PDFSHXTEXT=0`, `PUBLISHOPEN=0`, `PUBLISHVIEW=0`, `PLOTNOTIFY=0`, and `VIEWPLOTDETAILS=0` on the conversion document. A warning in `plot_results.json.layoutWarnings` means that the particular AutoCAD release rejected a setting; inspect the sample PDF rather than assuming fidelity.
