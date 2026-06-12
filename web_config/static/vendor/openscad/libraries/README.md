OpenSCAD Library Vendor Files
=============================

This directory contains OpenSCAD libraries made available to the browser-side
OpenSCAD WASM renderer.

Included libraries:

- `MCAD/`: OpenSCAD MCAD library from https://github.com/openscad/MCAD
  - Source commit: bd0a7ba3f042bfbced5ca1894b236cea08904e26
  - License: LGPL-2.1, see `MCAD/lgpl-2.1.txt`

At render time, OpenCAD writes these files into the OpenSCAD WASM virtual file
system so statements like `use <MCAD/gears.scad>` can resolve.
