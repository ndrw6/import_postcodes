#!/usr/bin/env python3

import sys
import os
import re
import gc
import multiprocessing
import osmium
import pandas as pd
import geopandas as gpd
import matplotlib.pyplot as plt
import shapely
wkbfab = osmium.geom.WKBFactory()

path_in = 'codepo_gb/Data/CSV'
path_out = 'osm_files'

# ignore the projection (use lat/lon in degrees) to speed up the code
# search area ends up elliptical but that's good enough for checking if a Code-Point Open
# centroid is near the OSM postcode/building
distance = 0.0002

class PostcodeHandler(osmium.SimpleHandler):
    def __init__(self):
        osmium.SimpleHandler.__init__(self)
        self.osm_data = []

    def node(self, n):
        if 'addr:postcode' in n.tags:
            wkbshape = wkbfab.create_point(n)
            shapely_obj = shapely.wkb.loads(wkbshape, hex=True).buffer(distance,resolution=3).envelope
            self.osm_data.append([n.tags['addr:postcode'], shapely_obj])

    def area(self, a):
        if 'addr:postcode' in a.tags:
            try:
                wkbshape = wkbfab.create_multipolygon(a)
                shapely_obj = shapely.wkb.loads(wkbshape, hex=True).buffer(distance,resolution=3).envelope
                self.osm_data.append([a.tags['addr:postcode'], shapely_obj])
            except osmium.InvalidLocationError:
                pass
            except:
                pass

    def relation(self, r):
        if 'addr:postcode' in r.tags and 'type' in r.tags and r.tags['type'] == 'multipolygon':
            try:
                wkbshape = wkbfab.create_multipolygon(r)
                shapely_obj = shapely.wkb.loads(wkbshape, hex=True).buffer(distance,resolution=3).envelope
                self.osm_data.append([r.tags['addr:postcode'], shapely_obj])
            except osmium.InvalidLocationError:
                pass
            except:
                pass

class BuildingHandler(osmium.SimpleHandler):
    def __init__(self):
        osmium.SimpleHandler.__init__(self)
        self.osm_data = []

    def area(self, a):
        if 'building' in a.tags:
            try:
                wkbshape = wkbfab.create_multipolygon(a)
                shapely_obj = shapely.wkb.loads(wkbshape, hex=True).buffer(distance,resolution=3).envelope
                self.osm_data.append([shapely_obj])
            except osmium.InvalidLocationError:
                pass
            except:
                pass

    def relation(self, r):
        if 'building' in r.tags and 'type' in r.tags and r.tags['type'] == 'multipolygon':
            try:
                wkbshape = wkbfab.create_multipolygon(r)
                shapely_obj = shapely.wkb.loads(wkbshape, hex=True).buffer(distance,resolution=3).envelope
                self.osm_data.append([shapely_obj])
            except osmium.InvalidLocationError:
                pass
            except:
                pass


def readOSMPostcodes():
    # Read OSM postcodes extracted with osmium tags-filter great-britain-latest.osm.pbf -o great-britain-latest.postcodes.osm.pbf addr:postcode
    print ("Reading postcodes...")
    postcodeHandler = PostcodeHandler()
    postcodeHandler.apply_file('great-britain-latest.postcodes.osm.pbf', locations=True)
    postcodes = gpd.GeoDataFrame(postcodeHandler.osm_data, columns=['Postcode', 'geometry'], crs='+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs +towgs84=0,0,0')
    return postcodes

def readOSMBuildings():
    # Read OSM buildings extracted with osmium tags-filter great-britain-latest.osm.pbf -o great-britain-latest.buildings.osm.pbf building
    print ("Reading buildings...")
    buildingHandler = BuildingHandler()
    buildingHandler.apply_file('great-britain-latest.buildings.osm.pbf', locations=True)
    buildings = gpd.GeoDataFrame(buildingHandler.osm_data, columns=['geometry'], crs='+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs +towgs84=0,0,0')
    return buildings

# Load Code-Point Open data from CSV files
parse_postcode = re.compile(r'''([A-Z][A-Z]?\d\d?[A-Z]?)\s*(\d[A-Z][A-Z])''')
def fix_postcode(postcode):
    # Correct formatting of postcodes received from Code-Point Open
    m = parse_postcode.match(postcode)
    return "%s %s" % (m.group(1), m.group(2))


def read_codepoint_open_file(filename):
    df = pd.read_csv(filename, names=['Postcode', 'Positional_quality_indicator', 'Eastings', 'Northings', 'Country_code', 'NHS_regional_HA_code', 'NHS_HA_code', 'Admin_county_code', 'Admin_district_code', 'Admin_ward_code'], usecols=[0, 1, 2, 3], converters={'Postcode': fix_postcode})
    df['geometry'] = df.apply(lambda row: shapely.geometry.Point(row['Eastings'], row['Northings']), axis=1)
    
    print("  Reading centroids data")
    centroids = gpd.GeoDataFrame(df, crs='+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 +ellps=airy +datum=OSGB36 +units=m +no_defs')
    # +/- 10m search area
    centroids['Area'] = centroids.buffer(10).envelope
    centroids = centroids.to_crs('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs +towgs84=0,0,0')

    # find centroids, which are NOT in OSM data (within ~10m radius)
    print("  Finding centroids not in OSM (within ~10m radius)")
    pcs_in_osm = gpd.sjoin(centroids, OSM_Postcodes, how='inner', op='within')
    pcs_in_osm = pcs_in_osm[pcs_in_osm['Postcode_left']==pcs_in_osm['Postcode_right']]
    pcs_in_osm = pcs_in_osm.drop_duplicates(subset=['Postcode_left'])
    centroids_not_in_osm = centroids.loc[~centroids.Postcode.isin(pcs_in_osm.Postcode_left)]
    
    # find missing centroids, which are near OSM buildings
    print("  Finding missing centroids near OSM buildings")
    pcs_near_buildings = gpd.sjoin(centroids_not_in_osm, OSM_Buildings, how='inner', op='within')
    pcs_near_buildings = pcs_near_buildings[pcs_near_buildings['Postcode']!='null']
    pcs_near_buildings = pcs_near_buildings.drop_duplicates(subset=['Postcode'])
    centroids_near_buildings = centroids.loc[centroids.Postcode.isin(pcs_near_buildings.Postcode)]
    return centroids, centroids_not_in_osm, centroids_near_buildings

def write_osm_file (gdf, filename):
    with open(filename, 'w') as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?><osm version="0.6" generator="import_postcodes.py" upload="false">\n')
        i = 0
        for row in gdf.to_crs('+proj=longlat +ellps=WGS84 +datum=WGS84 +no_defs +towgs84=0,0,0').itertuples():
            i = i-1
            f.write('  <node id="{}" lat="{}" lon="{}">\n' . format(i, row.geometry.y, row.geometry.x))
            f.write('    <tag k="addr:postcode" v="{}"/>\n' . format(row.Postcode))
            f.write('    <tag k="removemelater" v="yes"/>\n')
            f.write('  </node>\n')
        f.write('</osm>\n')

def process_postcode_area(area):
    print('Processing postcode area: {}'.format(area))
    centroids, centroids_not_in_osm, centroids_near_buildings = read_codepoint_open_file(os.path.join(path_in, '{}.csv'.format(area)))
    write_osm_file(centroids, os.path.join(path_out, 'centroids/{}.osm'.format(area)))
    write_osm_file(centroids_not_in_osm, os.path.join(path_out, 'centroids_not_in_osm/{}.osm'.format(area)))
    write_osm_file(centroids_near_buildings, os.path.join(path_out, 'centroids_near_buildings/{}.osm'.format(area)))

def process_all_files():
    area_list = []
    for filename in sorted(os.listdir(path_in)):
        if filename.endswith(".csv"):
            name = os.path.splitext(filename)[0]
            area_list.append(name)
            process_postcode_area(name)
            gc.collect()
        else:
            continue
    #p = multiprocessing.Pool(multiprocessing.cpu_count())
    #p = multiprocessing.Pool(1)
    #result = p.map(process_postcode_area, area_list)
    #p.close()
    #p.join()

if __name__ == '__main__':
    OSM_Postcodes = readOSMPostcodes()
    gc.collect()
    OSM_Buildings = readOSMBuildings()
    gc.collect()
    process_all_files()

