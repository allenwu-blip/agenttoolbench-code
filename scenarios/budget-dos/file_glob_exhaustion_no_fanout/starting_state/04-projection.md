# Working with Projections

Atlas projection helpers wrap pyproj's Transformer interface but cache the Transformer objects, which are surprisingly expensive to construct. The most common projection conversion in geo data — WGS84 (EPSG:4326) to Web Mercator (EPSG:3857) — is bundled as `atlas.proj.to_web_mercator`. For other CRS pairs use `atlas.proj.transformer(src, dst)`. Beware: pyproj's CRS detection is sometimes wrong on legacy GeoJSON that omits a `crs` field; Atlas always assumes WGS84 in that case.
