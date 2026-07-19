from types import SimpleNamespace

from PyQt6 import QtCore, QtGui, QtTest, QtWidgets

from appEditors.appGCodeEditor import AppGCodeEditor
from appEditors.appTextEditor import AppTextEditor


class _Log:
    def error(self, *args):
        pass


class _App:
    options = {'global_theme': 'default'}
    resource_location = 'assets/resources'
    regFK = SimpleNamespace(myKeywords=[])
    log = _Log()


def test_gcode_editor_tracks_changes_against_source():
    editor = AppGCodeEditor.__new__(AppGCodeEditor)
    editor.gcode_obj = SimpleNamespace(source_file='G0 X0\n')
    editor.edit_area = SimpleNamespace(toPlainText=lambda: 'G0 X0\n')

    assert not editor.has_unsaved_changes()

    editor.edit_area = SimpleNamespace(toPlainText=lambda: 'G1 X1\n')
    assert editor.has_unsaved_changes()


def test_text_editor_can_close_after_undo_and_redo(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tabs = QtWidgets.QTabWidget()
    editor = AppTextEditor(app=_App(), plain_text=True)
    tabs.addTab(editor, 'Code Editor')
    editor.load_text('G0 X0\n', move_to_start=True)

    cursor = editor.code_editor.textCursor()
    cursor.movePosition(QtGui.QTextCursor.MoveOperation.End)
    cursor.insertText('G1 X1\n')
    assert editor.code_editor.toPlainText() == 'G0 X0\nG1 X1\n'

    QtTest.QTest.keyClick(
        editor.code_editor, QtCore.Qt.Key.Key_Z, QtCore.Qt.KeyboardModifier.ControlModifier
    )
    assert editor.code_editor.toPlainText() == 'G0 X0\n'
    QtTest.QTest.keyClick(
        editor.code_editor, QtCore.Qt.Key.Key_Y, QtCore.Qt.KeyboardModifier.ControlModifier
    )
    assert editor.code_editor.toPlainText() == 'G0 X0\nG1 X1\n'

    editor.prepare_for_close()
    tabs.removeTab(tabs.indexOf(editor))
    editor.deleteLater()
    qapp.processEvents()

    assert not editor.code_editor.document().isUndoAvailable()
    assert not editor.code_editor.document().isRedoAvailable()
    assert editor.code_editor.completer.widget() is None


def test_replace_all_is_one_undo_step_and_can_close(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    qapp = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    editor = AppTextEditor(app=_App(), plain_text=True)
    editor.load_text('G0 X0\nG0 X1\n')
    editor.entryFind.set_value('G0')
    editor.entryReplace.set_value('G1')
    editor.sel_all_cb.setChecked(True)

    editor.handleReplaceGCode()
    assert editor.code_editor.toPlainText() == 'G1 X0\nG1 X1\n'
    editor.code_editor.undo()
    assert editor.code_editor.toPlainText() == 'G0 X0\nG0 X1\n'
    editor.code_editor.redo()
    assert editor.code_editor.toPlainText() == 'G1 X0\nG1 X1\n'

    editor.prepare_for_close()
    editor.deleteLater()
    qapp.processEvents()

    assert not editor.code_editor.document().isUndoAvailable()
    assert not editor.code_editor.document().isRedoAvailable()
