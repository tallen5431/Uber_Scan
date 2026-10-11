#!/usr/bin/env python3
"""The NucBox's street index, made once from the Georgia file it already has.

Run ON THE NUCBOX (Ubuntu 24.04), where the extract is:

    sudo apt install osmium-tool
    python3 tools/street_index.py ~/osrm/georgia-latest.osm.pbf ~/streets.json

and set NUCBOX_STREETS_FILE=~/streets.json in the environment of the NucBox's
own server.js (README, "The NucBox at home"). Nothing here downloads
anything: it reads the file it is given.

WHAT IT KEEPS. Every way inside the driver's metro (BBOX, below) that is a
street a car is driven on (KEEP) and has a name. Three osmium-tool commands
cut the file to that area, to those ways, and write each way with its nodes'
coordinates on it (OPL, osmium's line-per-object text); this reads that text
and writes one JSON file: the names, every node the kept ways use (once, so
two ways that share a node share it here — that is how a junction is found),
and each way as its names and its nodes. Coordinates are integers of a
millionth of a degree, each the difference from the one before, which is what
keeps the file small. Python's standard library only.

    --bbox W,S,E,N   another area (degrees)
    --opl FILE       read osmium's OPL from FILE instead of running osmium
                     (the suites use it where osmium is not installed)
    --keep-opl FILE  keep osmium's OPL there too (how tests/fixtures/
                     streets.opl was made, and how the suite holds it to
                     what osmium writes now)
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

FORMAT = 'uberscan-streets/1'

# Every town the week's 1,166 cards name, Cartersville and White in the north-
# west to Suwanee and Lithonia in the east and Union City in the south, with a
# margin: a card's disc reaches its own distance past where the car was.
BBOX = (-85.00, 33.50, -83.95, 34.40)

# The streets a car is driven on, and so the ones Uber names a corner by.
# `service` is kept: only NAMED ways are kept at all, and a named service way
# is an apartment complex's or a shopping centre's own drive — where a
# dropoff often is. Not kept: footway, path, cycleway, steps, pedestrian,
# track, bridleway, construction and proposed — a named footpath crossing a
# street is not a corner a car stops at, and kept it would be a second
# "place where A meets B" that is not one.
KEEP = ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary',
        'primary_link', 'secondary', 'secondary_link', 'tertiary',
        'tertiary_link', 'unclassified', 'residential', 'living_street',
        'service')

# The tags a street's name is read from, each split on ";" as OSM writes a
# list. `ref` ("US 41") is not a name Uber prints a corner by.
NAME_TAGS = ('name', 'alt_name', 'official_name')

ESC = re.compile(r'%([0-9a-fA-F]+)%')


def unescape(s):
    """OPL writes a space, comma, equals sign or percent as %hex%."""
    return ESC.sub(lambda m: chr(int(m.group(1), 16)), s)


def tags_of(field):
    out = {}
    if not field:
        return out
    for kv in field.split(','):
        k, _, v = kv.partition('=')
        out[unescape(k)] = unescape(v)
    return out


def osmium(cmd):
    try:
        return subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, text=True)
    except FileNotFoundError:
        sys.exit('osmium is not installed: sudo apt install osmium-tool')
    except subprocess.CalledProcessError as e:
        sys.exit('%s failed: %s' % (' '.join(cmd[:2]), e.stderr.strip()))


def opl_from_osmium(source, bbox, work):
    """The three osmium commands, into `work`; the OPL file's path."""
    area = os.path.join(work, 'area.osm.pbf')
    roads = os.path.join(work, 'roads.osm.pbf')
    opl = os.path.join(work, 'roads.opl')
    osmium(['osmium', 'extract', '--bbox', ','.join('%g' % v for v in bbox),
            '--strategy', 'complete_ways', '--overwrite', '-o', area, source])
    osmium(['osmium', 'tags-filter', '--overwrite', '-o', roads, area,
            'w/highway=' + ','.join(KEEP)])
    osmium(['osmium', 'add-locations-to-ways', '--overwrite', '-f', 'opl',
            '-o', opl, roads])
    return opl


def index_of(lines, bbox, source):
    """The index, and what was dropped and why, from OPL lines."""
    names, name_at = [], {}
    nodes, node_at = [], {}
    ways = []
    dropped = {'unnamed': 0, 'other highway': 0, 'no location': 0}
    for line in lines:
        if not line.startswith('w'):
            continue
        fields = {}
        for f in line.rstrip('\n').split(' '):
            if f:
                fields[f[0]] = f[1:]
        tags = tags_of(fields.get('T', ''))
        if tags.get('highway') not in KEEP:
            dropped['other highway'] += 1
            continue
        said = []
        for k in NAME_TAGS:
            for v in tags.get(k, '').split(';'):
                v = v.strip()
                if v and v not in said:
                    said.append(v)
        if not said:
            dropped['unnamed'] += 1
            continue
        refs = []
        for ref in (fields.get('N') or '').split(','):
            m = re.match(r'^n(-?\d+)x(-?[\d.]+)y(-?[\d.]+)$', ref)
            if not m:
                continue
            nid = int(m.group(1))
            if nid not in node_at:
                node_at[nid] = len(nodes)
                nodes.append((round(float(m.group(2)) * 1e6), round(float(m.group(3)) * 1e6)))
            if not refs or refs[-1] != node_at[nid]:
                refs.append(node_at[nid])
        if len(refs) < 2:
            dropped['no location'] += 1
            continue
        ids = []
        for n in said:
            if n not in name_at:
                name_at[n] = len(names)
                names.append(n)
            ids.append(name_at[n])
        ways.append([ids, [refs[0]] + [refs[i] - refs[i - 1] for i in range(1, len(refs))]])
    flat, px, py = [], 0, 0
    for x, y in nodes:
        flat.append(x - px)
        flat.append(y - py)
        px, py = x, y
    doc = {'format': FORMAT, 'e': 6, 'bbox': list(bbox), 'highways': list(KEEP),
           'nameTags': list(NAME_TAGS), 'source': os.path.basename(source),
           'names': names, 'nodes': flat, 'ways': ways}
    return doc, dropped


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('source', help='the .osm.pbf (or .osm) to read')
    ap.add_argument('out', help='where to write the index (JSON)')
    ap.add_argument('--bbox', help='W,S,E,N in degrees (default: the metro)')
    ap.add_argument('--opl', help="read osmium's OPL from this file instead")
    ap.add_argument('--keep-opl', help="keep osmium's OPL in this file too")
    a = ap.parse_args(argv)
    bbox = BBOX
    if a.bbox:
        bbox = tuple(float(v) for v in a.bbox.split(','))
        if len(bbox) != 4:
            sys.exit('--bbox is W,S,E,N')
    t0 = time.time()
    work = None
    try:
        if a.opl:
            opl = a.opl
        else:
            work = tempfile.mkdtemp(prefix='streets-')
            opl = opl_from_osmium(a.source, bbox, work)
            if a.keep_opl:
                shutil.copyfile(opl, a.keep_opl)
        t1 = time.time()
        with open(opl, encoding='utf-8') as f:
            doc, dropped = index_of(f, bbox, a.source)
    finally:
        if work:
            shutil.rmtree(work, ignore_errors=True)
    tmp = a.out + '.part'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, separators=(',', ':'), ensure_ascii=False)
    os.replace(tmp, a.out)
    print('kept %d ways, %d nodes, %d names; dropped %s; osmium %.1f s, '
          'index %.1f s; wrote %d bytes to %s'
          % (len(doc['ways']), len(doc['nodes']) // 2, len(doc['names']),
             ', '.join('%d %s' % (v, k) for k, v in dropped.items()),
             t1 - t0, time.time() - t1, os.path.getsize(a.out), a.out),
          file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
