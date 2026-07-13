import json

import pytest

from appCommon.tool_database_seed import build_factory_tool_database, seed_factory_tool_database
from defaults import AppDefaults


@pytest.fixture
def options():
    return AppDefaults.factory_defaults.copy()


def test_factory_database_contains_fr4_and_labeled_laser_presets(options):
    database = build_factory_tool_database(options)
    names = [tool['name'] for tool in database.values()]

    assert any(name.startswith('FR-4 isolation') for name in names)
    assert any('FoxAlien 60deg V-bit, 0.10mm tip, 1/8in shank' in name for name in names)
    assert any(name.startswith('FR-4 drill') for name in names)
    assert not any('FR-1' in name for name in names)
    assert all(
        'TEST GRID' in name and 'GRBL $30=1000' in name
        for name in names if '10W diode' in name
    )


def test_factory_database_converts_metric_linear_values_to_inches(options):
    metric = build_factory_tool_database(options, 'MM')
    imperial = build_factory_tool_database(options, 'IN')

    metric_tool = metric['1']
    imperial_tool = imperial['1']
    assert imperial_tool['tooldia'] == pytest.approx(metric_tool['tooldia'] / 25.4)
    assert imperial_tool['data']['tools_mill_feedrate'] == pytest.approx(
        metric_tool['data']['tools_mill_feedrate'] / 25.4
    )
    assert imperial_tool['data']['tools_mill_spindlespeed'] == 12000


def test_laser_presets_do_not_participate_in_automatic_milling_matches(options):
    database = build_factory_tool_database(options)
    laser_tools = [tool for tool in database.values() if '10W diode' in tool['name']]

    assert laser_tools
    assert all(tool['data']['tool_target'] == 0 for tool in laser_tools)
    assert all(tool['data']['tools_mill_tool_shape'] == 6 for tool in laser_tools)
    assert all(tool['data']['tools_mill_laser_on'] == 'M4' for tool in laser_tools)


def test_seed_only_creates_a_missing_database(tmp_path, options):
    database_path = tmp_path / 'tools.FlatDB'
    assert seed_factory_tool_database(database_path, options) is True
    seeded = json.loads(database_path.read_text())
    assert seeded

    database_path.write_text('{"user": true}')
    assert seed_factory_tool_database(database_path, options) is False
    assert json.loads(database_path.read_text()) == {'user': True}
