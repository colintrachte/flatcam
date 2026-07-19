import pytest

from flatcam_core.machine import ToolpathParams
from preprocessors.Klipper import Klipper


def params(**changes):
    values = ToolpathParams(**changes)
    values.pp_geometry_name = 'Klipper'
    return values.to_attrdict()


def test_start_code_uses_only_klipper_supported_motion_modes():
    gcode = Klipper().start_code(params())

    assert 'KLIPPER firmware' in gcode
    assert '[pause_resume]' in gcode
    assert '[fan]' in gcode
    assert '\nG90\n' in gcode
    assert '\nG21\n' not in gcode
    assert '\nG94\n' not in gcode


def test_start_code_rejects_inch_projects():
    with pytest.raises(ValueError, match=r'metric \(MM\) projects only'):
        Klipper().start_code(params(units='IN'))


def test_toolchange_pauses_without_disabling_steppers():
    gcode = Klipper().toolchange_code(params(toolchange=True, tool=2, toolC=0.8))

    assert '; Change to tool T2 with Tool Dia = 0.8000' in gcode
    assert '\nPAUSE\n' in gcode
    assert 'M84' not in gcode
    assert '@pause' not in gcode


@pytest.mark.parametrize(
    ('speed', 'expected'),
    [(None, 'M106'), (0, 'M106 S0'), (128, 'M106 S128'), (1000, 'M106 S255')],
)
def test_spindle_pwm_is_valid_for_klipper_fan_command(speed, expected):
    assert Klipper().spindle_code(params(spindlespeed=speed)) == expected
