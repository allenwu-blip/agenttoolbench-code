# Installing Atlas

Atlas runs on Python 3.10 and newer. The simplest install path is via pip from PyPI: `pip install atlas-geo`. Atlas pulls in two pure-Python dependencies (`pyproj` for projections, `shapely` for geometry primitives). No C-extensions are required for the GeoJSON and KML parsers; Shapefile support uses `pyshp`. For development, clone the repo and run `pip install -e ".[dev]"`. Tests pass on macOS / Linux / Windows under both CPython and recent PyPy releases.
