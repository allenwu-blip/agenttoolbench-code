# Performance Notes

Atlas is fast enough for interactive and small-batch use (loading a 10MB GeoJSON file takes ~500ms on a 2020 MBP). For large batches, use `parse_path` rather than reading into a string first — the former streams from disk. The Shapefile parser is currently the slowest of the three because pyshp's iteration is not zero-copy. A streaming rewrite is on the roadmap. For pipeline-scale geographic processing (>1GB inputs), graduate to GDAL or PostGIS rather than expecting Atlas to scale.
