#!/usr/bin/env python 
import os, sys, time, json, requests, logging
import re, traceback, argparse, copy, bisect
from xml.etree import ElementTree
#from hysds_commons.job_utils import resolve_hysds_job
#from hysds.celery import app
from shapely.geometry import Polygon
from shapely.ops import cascaded_union
import datetime
import dateutil.parser
from datetime import datetime, timedelta
import groundTrack
from osgeo import ogr, osr
import lightweight_water_mask
import util
from util import ACQ
import urllib.request


GRQ_URL="http://100.64.134.208:9200/"

logger = logging.getLogger(os.path.splitext(os.path.basename(__file__))[0])
logger.setLevel(logging.INFO)
#logger.addFilter(LogFilter())

SLC_RE = re.compile(r'(?P<mission>S1\w)_IW_SLC__.*?' +
                    r'_(?P<start_year>\d{4})(?P<start_month>\d{2})(?P<start_day>\d{2})' +
                    r'T(?P<start_hour>\d{2})(?P<start_min>\d{2})(?P<start_sec>\d{2})' +
                    r'_(?P<end_year>\d{4})(?P<end_month>\d{2})(?P<end_day>\d{2})' +
                    r'T(?P<end_hour>\d{2})(?P<end_min>\d{2})(?P<end_sec>\d{2})_.*$')

BASE_PATH = os.path.dirname(__file__)
MISSION = 'S1A'


def download_orbit_file(url, file_name):
    downloaded = False
    try:
        urllib.request.urlretrieve(url, file_name)
        downloaded = True
    except Exception as err:
        logger.info("Error Downloading Orbit File : %s" %url)
        logger.info(sys.exc_info())
    return downloaded

def get_groundTrack_footprint(tstart, tend, orbit_file):
    mission = MISSION
    gt_footprint = []
    gt_footprint_temp= groundTrack.get_ground_track(tstart, tend, mission, orbit_file)
    for g in gt_footprint_temp:
        gt_footprint.append(list(g))

    gt_footprint.append(gt_footprint[0])

    #logger.info("gt_footprint : %s:" %gt_footprint)
    geojson = {"type":"Polygon", "coordinates": [gt_footprint]}
    return geojson

def water_mask_check(acq_info, grouped_matched_orbit_number,  aoi_location, orbit_file=None):

    result = False
    if not aoi_location:
        logger.info("water_mask_check FAILED as aoi_location NOT found")
        return False
    try:
        result = water_mask_test1(acq_info, grouped_matched_orbit_number,  aoi_location, orbit_file)
    except Exception as err:
        traceback.print_exc()
    return result


def get_time(t):
    try:
        return datetime.strptime(t, '%Y-%m-%dT%H:%M:%S')
    except ValueError as e:
        t1 = datetime.strptime(t, '%Y-%m-%dT%H:%M:%S.%f').strftime("%Y-%m-%d %H:%M:%S")
        return datetime.strptime(t1, '%Y-%m-%d %H:%M:%S')

def get_area_from_orbit_file(tstart, tend, orbit_file, aoi_location):
    water_area = 0
    land_area = 0
    logger.info("tstart : %s  tend : %s" %(tstart, tend))
    geojson = get_groundTrack_footprint(tstart, tend, orbit_file)
    intersection, int_env = util.get_intersection(aoi_location, geojson)
    logger.info("intersection : %s" %intersection)
    land_area = lightweight_water_mask.get_land_area(intersection)
    logger.info("get_land_area(geojson) : %s " %land_area)
    water_area = lightweight_water_mask.get_water_area(intersection)

    logger.info("covers_land : %s " %lightweight_water_mask.covers_land(geojson))
    logger.info("covers_water : %s "%lightweight_water_mask.covers_water(geojson))
    logger.info("get_land_area(geojson) : %s " %land_area)
    logger.info("get_water_area(geojson) : %s " %water_area)    
    

    return land_area, water_area

def get_aoi_area_multipolygon(geojson, aoi_location):
    water_area = 0
    land_area = 0

    polygon_type = geojson["type"]

    if polygon_type == "MultiPolygon":
        coordinates = geojson["coordinates"]
        union_land = 0
        union_water = 0
        for i in range(len(coordinates)):
            cord =ange_coordinate_direction(coordinates[i])
            geojson_new = {"type":"Polygon", "coordinates": [cord]}
            land, water = get_aoi_area_polygon(geojson_new, aoi_location)
            union_land += land
            union_water += water
        return union_land, union_water

    else:
        return get_aoi_area_polygon(geojson, aoi_location)

def get_aoi_area_polygon(geojson, aoi_location):
    water_area = 0
    land_area = 0

    intersection, int_env = util.get_intersection(aoi_location, geojson)
    logger.info("intersection : %s" %intersection)
    try:
        land_area = lightweight_water_mask.get_land_area(intersection)
        logger.info("get_land_area(geojson) : %s " %land_area)
    except Exception as err:
        logger.info("Getting Land Area Failed for geojson : %s" %intersection)
        cord = intersection["coordinates"][0]
        rotated_cord = [cord[::-1]]
        rotated_intersection = {"type":"Polygon", "coordinates": rotated_cord}
        logger.info("rorated_intersection : %s" %rotated_intersection)
        
        try:
            land_area = lightweight_water_mask.get_land_area(rotated_intersection)
            logger.info("get_land_area(geojson) : %s " %land_area)
        except Exception as err:
            logger.info("Getting Land Area Failed AGAIN for rotated geojson : %s" %rotated_intersection)
            logger.info(sys.exc_info())
    '''
    try:
        water_area = lightweight_water_mask.get_water_area(intersection)
    except Exception as err:
        logger.info("Getting Water Area Failed for geojson : %s" %intersection)
        logger.info(sys.exc_info())
    try:
        logger.info("covers_land : %s " %lightweight_water_mask.covers_land(intersection))
        logger.info("covers_water : %s "%lightweight_water_mask.covers_water(intersection))
    except Exception as err:
        logger.info("Getting covers land/water Failed for geojson : %s" %intersection)
        logger.info(sys.exc_info()
    '''
    logger.info("get_land_area(geojson) : %s " %land_area)
    logger.info("get_water_area(geojson) : %s " %water_area)


    return land_area, water_area



def change_coordinate_direction(cord):
    cord_area = util.get_area(cord)
    if not cord_area>0:
        logger.info("change_coordinate_direction : coordinates are not clockwise, reversing it")
        cord = [cord[::-1]]
        logger.info(cord)
        cord_area = util.get_area(cord)
        if not cord_area>0:
            logger.info("change_coordinate_direction. coordinates are STILL NOT  clockwise")
    else:
        logger.info("change_coordinate_direction: coordinates are already clockwise")

    return cord


def change_union_coordinate_direction(union_geom):
    logger.info("change_coordinate_direction")
    coordinates = union_geom["coordinates"]
    logger.info("Type of union polygon : %s of len %s" %(type(coordinates), len(coordinates)))
    for i in range(len(coordinates)):
        cord = coordinates[i]
        cord_area = util.get_area(cord)
        if not cord_area>0:
            logger.info("change_coordinate_direction : coordinates are not clockwise, reversing it")
            cord = [cord[::-1]]
            logger.info(cord)
            cord_area = util.get_area(cord)
            if not cord_area>0:
                logger.info("change_coordinate_direction. coordinates are STILL NOT  clockwise")
            union_geom["coordinates"][i] = cord
        else:
            logger.info("change_coordinate_direction: coordinates are already clockwise")

    return union_geom

def water_mask_test1(acq_info, grouped_matched_orbit_number,  aoi_location, orbit_file = None):

    logger.info("\n\n\nWATER MASK TEST\n")

    passed = False
    starttimes = []
    endtimes = []
    polygons = []
    acqs_land = []
    acqs_water = []
    gt_polygons = []
    logger.info("water_mask_test1 : aoi_location : %s" %aoi_location)
    acq_area_array = []
    gt_area_array = []
    for pv in grouped_matched_orbit_number:
        acq_ids = grouped_matched_orbit_number[pv]
        for acq_id in acq_ids:
            logger.info("\n%s : %s" %(pv, acq_id))
            acq = acq_info[acq_id]
            starttimes.append(get_time(acq.starttime))
            endtimes.append(get_time(acq.endtime))

            logger.info("ACQ start time : %s " %acq.starttime)
            logger.info("ACQ end time : %s" %acq.endtime)
            land, water = get_aoi_area_multipolygon(acq.location, aoi_location)
            acq_area_array.append(land)
            logger.info("Area from acq.location : %s" %land)
            polygons.append(acq.location)

            if orbit_file:
                gt_geojson = get_groundTrack_footprint(get_time(acq.starttime), get_time(acq.endtime), orbit_file)
                gt_polygons.append(gt_geojson)
                land, water = get_aoi_area_multipolygon(gt_geojson, aoi_location)
                logger.info("Area from gt_geojson : %s" %land)
                gt_area_array.append(land)

    logger.info("Sum of acq.location area : %s" %sum(acq_area_array))
    logger.info("Sum of gt location area : %s" %sum(gt_area_array))
    total_land = 0
    total_water = 0
   
    logger.info("Calculating Union")
    if orbit_file:
        ''' First Try Without Orbit File '''
        union_polygon = util.get_union_geometry(polygons)
        #union_polygon = change_coordinate_direction(union_polygon)
        logger.debug("Type of union polygon : %s of len %s" %(type(union_polygon["coordinates"]), len(union_polygon["coordinates"])))

        logger.info("water_mask_test1 without Orbit File")
        union_land, union_water = get_aoi_area_multipolygon(union_polygon, aoi_location)
        logger.info("water_mask_test1 without Orbit File: union_land : %s union_water : %s" %(union_land, union_water))




        ''' Now Try With Orbit File '''
        logger.info("water_mask_test1 with Orbit File")
        union_gt_polygon = util.get_union_geometry(gt_polygons)
        #union_gt_polygon = change_coordinate_direction(union_gt_polygon)
        #logger.debug("water_mask_test1 : union_gt_polygon : %s" %union_gt_polygon)
        #get lowest starttime minus 10 minutes as starttime
        #tstart = getUpdatedTime(sorted(starttimes)[0], -10)
        tstart = sorted(starttimes)[0]
        logger.info("tstart : %s" %tstart)
        tend = getUpdatedTime(sorted(endtimes, reverse=True)[0], 10)
        tend = sorted(endtimes, reverse=True)[0]
        logger.info("tend : %s" %tend)
        aoi_gt_geojson = get_groundTrack_footprint(tstart, tend, orbit_file)
        #aoi_gt_polygon = change_coordinate_direction(aoi_gt_geojson)
        #logger.debug("water_mask_test1 : aoi_gt_geojson : %s" %aoi_gt_geojson)
        union_land, union_water = get_aoi_area_multipolygon(union_gt_polygon, aoi_location)
        logger.info("water_mask_test1 with Orbit File: union_land : %s union_water : %s" %(union_land, union_water))
        
        aoi_land, aoi_water = get_aoi_area_multipolygon(aoi_gt_geojson, aoi_location)
        logger.info("water_mask_test1 with Orbit File: aoi_land : %s aoi_water : %s" %(aoi_land, aoi_water))
        return isTrackSelected(union_land, aoi_land)
    else:        
        union_polygon = util.get_union_geometry(polygons)
        union_polygon = change_coordinate_direction(union_polygon)
        logger.info("Type of union polygon : %s of len %s" %(type(union_polygon["coordinates"]), len(union_polygon["coordinates"])))

        logger.info("water_mask_test1 without Orbit File : union_geojson : %s" %union_geojson)
        union_land, union_water = get_aoi_area_multipolygon(union_polygon, aoi_location)
        logger.info("water_mask_test1 without Orbit File: union_land : %s union_water : %s" %(union_land, union_water))
        aoi_land, aoi_water = get_aoi_area_multipolygon(aoi_location, aoi_location)
        logger.info("water_mask_test1 without Orbit File: aoi_land : %s aoi_water : %s" %(aoi_land, aoi_water))

        return isTrackSelected(union_land, aoi_land)


def isTrackSelected(union_land, aoi_land):
    selected = False
    logger.info("Area of union of acquisition land = %s" %union_land)
    logger.info("Area of AOI land = %s" %aoi_land)
    if union_land == 0 or aoi_land == 0:
        logger.info("\nERROR : isTrackSelected : Returning as lands are Not correct")
        return False
    delta = abs(union_land - aoi_land)
    pctDelta = delta/union_land
    logger.info("delta : %s and pctDelta : %s" %(delta, pctDelta))
    if pctDelta <.02:
        logger.info("Track is SELECTED !!")
        return True
    logger.info("Track is NOT SELECTED !!")
    return False

def get_area_from_acq_location(geojson, aoi_location):
    logger.info("geojson : %s" %geojson)
    intersection, int_env = util.get_intersection(aoi_location, geojson)
    logger.info("intersection : %s" %intersection)
    land_area = lightweight_water_mask.get_land_area(intersection)
    water_area = lightweight_water_mask.get_water_area(intersection)

    logger.info("covers_land : %s " %lightweight_water_mask.covers_land(geojson))
    logger.info("covers_water : %s "%lightweight_water_mask.covers_water(geojson))
    logger.info("get_land_area(geojson) : %s " %land_area)
    logger.info("get_water_area(geojson) : %s " %water_area)


    return land_area, water_area


def getUpdatedTime(s, m):
    #date = dateutil.parser.parse(s, ignoretz=True)
    new_date = s + timedelta(minutes = m)
    return new_date


