#!/bin/sh

curl http://download.geofabrik.de/europe/great-britain-latest.osm.pbf --output great-britain-latest.osm.pbf
osmium tags-filter great-britain-latest.osm.pbf -o great-britain-latest.postcodes.osm.pbf --overwrite addr:postcode
osmium tags-filter great-britain-latest.osm.pbf -o great-britain-latest.buildings.osm.pbf --overwrite building
