# Shapefile Quirks

Shapefiles are the worst geographic format still in active use. They are five-file bundles (.shp, .shx, .dbf, .prj, .cpg), each governed by a different decades-old spec, and encoding handling is famously broken. Atlas's Shapefile parser only loads the .shp + .dbf (geometry + attrs) and assumes UTF-8 for attribute strings. If you have a Shapefile with a .cpg declaring something exotic, decode in your own code before calling Atlas. Roughly 30 percent of real-world Shapefiles I encounter have at least one encoding-related issue.
