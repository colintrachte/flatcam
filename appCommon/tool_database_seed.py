from copy import deepcopy
import os

import simplejson as json


MM_PER_INCH = 25.4


def _convert_mm(value, units):
    if str(units).upper() in {'IN', 'INCH'}:
        return value / MM_PER_INCH
    return value


def _target_data(options, target, prefixes):
    data = {
        'plot': True,
        'tool_target': target,
        'tol_min': 0.0,
        'tol_max': 0.0
    }
    for key, value in options.items():
        if any(key.startswith(prefix) for prefix in prefixes):
            data[key] = deepcopy(value)
    return data


def _preset(options, units, name, diameter_mm, target, prefixes, overrides, tolerance_mm=0.0):
    diameter = _convert_mm(diameter_mm, units)
    data = _target_data(options, target, prefixes)
    data.update(deepcopy(overrides))
    if tolerance_mm:
        tolerance = _convert_mm(tolerance_mm, units)
        data['tol_min'] = diameter - tolerance
        data['tol_max'] = diameter + tolerance
    return {
        'name': name,
        'tooldia': diameter,
        'data': data
    }


def build_factory_tool_database(options, units='MM'):
    """Build first-run tool presets from canonical metric source values."""
    linear = lambda value: _convert_mm(value, units)
    tools = []

    isolation_presets = [
        ('FR-4 isolation - 30deg V-bit, 0.10mm tip', 0.1429, 0.10, 30),
        ('FR-4 isolation - FoxAlien 60deg V-bit, 0.10mm tip, 1/8in shank', 0.1924, 0.10, 60)
    ]
    for name, effective_diameter, tip_diameter, angle in isolation_presets:
        tools.append(_preset(
            options, units, name, effective_diameter, 3,
            ('tools_mill_', 'tools_iso_'),
            {
                'tools_mill_tool_shape': 5,
                'tools_mill_cutz': -linear(0.08),
                'tools_mill_multidepth': False,
                'tools_mill_depthperpass': linear(0.08),
                'tools_mill_vtipdia': linear(tip_diameter),
                'tools_mill_vtipangle': angle,
                'tools_mill_feedrate': linear(120.0),
                'tools_mill_feedrate_z': linear(30.0),
                'tools_mill_spindlespeed': 12000,
                'tools_iso_passes': 1
            }
        ))

    milling_presets = [
        ('FR-4 milling - 0.40mm flat end mill', 0.40, 120.0, 12.0, 0.05),
        ('FR-4 milling - 0.80mm flat end mill', 0.80, 180.0, 20.0, 0.10),
        ('FR-4 milling - 1.00mm flat end mill', 1.00, 200.0, 25.0, 0.10),
        ('FR-4 milling - 1.60mm flat end mill', 1.60, 240.0, 30.0, 0.13),
        ('FR-4 milling - 3.175mm flat end mill', 3.175, 300.0, 30.0, 0.13)
    ]
    for name, diameter, feed, plunge, depth in milling_presets:
        tools.append(_preset(
            options, units, name, diameter, 1, ('tools_mill_',),
            {
                'tools_mill_tool_shape': 0,
                'tools_mill_multidepth': True,
                'tools_mill_depthperpass': linear(depth),
                'tools_mill_feedrate': linear(feed),
                'tools_mill_feedrate_z': linear(plunge),
                'tools_mill_spindlespeed': 12000
            }
        ))

    drill_presets = [
        ('FR-4 drill - 0.5 to 0.7mm carbide', 0.60, 0.10, 60.0),
        ('FR-4 drill - 0.8 to 1.0mm carbide', 0.90, 0.10, 80.0),
        ('FR-4 drill - 1.1 to 1.5mm carbide', 1.30, 0.20, 100.0),
        ('FR-4 drill - 1.6 to 2.0mm carbide', 1.80, 0.20, 120.0),
        ('FR-4 drill - 2.1 to 3.175mm carbide', 2.6375, 0.5375, 150.0)
    ]
    for name, diameter, tolerance, feed in drill_presets:
        tools.append(_preset(
            options, units, name, diameter, 2,
            ('tools_drill_', 'tools_mill_'),
            {
                'tools_drill_feedrate_z': linear(feed),
                'tools_drill_spindlespeed': 12000
            },
            tolerance_mm=tolerance
        ))

    laser_presets = [
        ('TEST GRID - 10W diode basswood engrave - GRBL $30=1000', 6000.0, 750),
        ('TEST GRID - 10W diode 3mm basswood cut, 1 pass - GRBL $30=1000', 300.0, 1000),
        ('TEST GRID - 10W diode corrugated card engrave - GRBL $30=1000', 6000.0, 400),
        ('TEST GRID - 10W diode 3.5mm card cut, 1 pass - GRBL $30=1000', 540.0, 1000),
        ('TEST GRID - 10W diode coated metal engrave - GRBL $30=1000', 4200.0, 1000),
        ('TEST GRID - 10W diode stainless mark - GRBL $30=1000', 720.0, 1000)
    ]
    for name, feed, power in laser_presets:
        tools.append(_preset(
            options, units, name, 0.08, 0, ('tools_mill_',),
            {
                'tools_mill_tool_shape': 6,
                'tools_mill_feedrate': linear(feed),
                'tools_mill_spindlespeed': power,
                'tools_mill_min_power': 0.0,
                'tools_mill_laser_on': 'M4',
                'tools_mill_ppname_g': 'GRBL_laser'
            }
        ))

    return {str(index): tool for index, tool in enumerate(tools, start=1)}


def seed_factory_tool_database(filename, options, units='MM'):
    """Create a factory tool database without replacing an existing file."""
    if os.path.exists(filename):
        return False
    with open(filename, 'x') as database_file:
        json.dump(build_factory_tool_database(options, units), database_file, indent=2)
    return True
