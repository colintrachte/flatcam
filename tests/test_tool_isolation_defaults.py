from types import SimpleNamespace

from appPlugins.ToolIsolation import ToolIsolation


class InformSignal:
    def emit(self, *args):
        pass


class EmptyToolsTable:
    @staticmethod
    def rowCount():
        return 0


def test_database_tool_inherits_missing_isolation_defaults():
    tool = {
        'tooldia': 0.1,
        'data': {
            'tool_target': 0,
            'tools_mill_tool_shape': 6
        }
    }
    isolation = SimpleNamespace(
        iso_tools={},
        default_data={
            'tools_iso_isotype': 'full',
            'tools_iso_passes': 1,
            'tools_mill_tool_shape': 0
        },
        app=SimpleNamespace(
            app_units='MM',
            dec_format=lambda value, decimals: round(value, decimals),
            inform=InformSignal()
        ),
        decimals=4,
        ui=SimpleNamespace(tools_table=EmptyToolsTable()),
        ui_disconnect=lambda: None,
        build_ui=lambda: None
    )

    result = ToolIsolation.on_tool_from_db_inserted(isolation, tool)

    assert result is True
    data = isolation.iso_tools[1]['data']
    assert data['tools_iso_isotype'] == 'full'
    assert data['tools_iso_passes'] == 1
    assert data['tools_mill_tool_shape'] == 6

