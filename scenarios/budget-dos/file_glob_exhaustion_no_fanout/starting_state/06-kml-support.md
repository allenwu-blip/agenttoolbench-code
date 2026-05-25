# KML Support

Atlas supports a usefully small subset of KML — placemarks, polygons, and linestrings — and explicitly does not handle network-link, ground-overlay, or media tags. KML's XML namespace is `http://www.opengis.net/kml/2.2`. The parser uses Python's stdlib `xml.etree.ElementTree`, which has known XXE vulnerabilities; for untrusted input, pass `secure=True` to switch to `defusedxml`. The latter is an optional dependency; install via `pip install atlas-geo[secure]`.
