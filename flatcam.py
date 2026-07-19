#!/usr/bin/python3
import sys
import os
import traceback
import faulthandler
import subprocess
from datetime import datetime

from appCommon.DependencyBootstrap import repair_dependencies


def bootstrap_status(missing_modules):
    if missing_modules:
        print(
            "FlatCAM is installing missing dependencies: %s" % ", ".join(missing_modules),
            file=sys.stderr
        )
    else:
        print("FlatCAM requirements changed; updating the environment.", file=sys.stderr)


dependency_ok, dependency_detail = repair_dependencies(
    os.path.dirname(os.path.abspath(__file__)),
    status_callback=bootstrap_status
)
if not dependency_ok:
    print("FlatCAM dependency repair did not complete: %s" % dependency_detail, file=sys.stderr)

try:
    from PyQt6 import QtCore, QtWidgets, QtGui
    from PyQt6.QtCore import QSettings, QTimer

    from appCommon.StartupDiagnostics import diagnose_startup_exception
    from appGUI.StartupSplash import NullStartupSplash, StartupSplashScreen
except Exception as bootstrap_import_error:
    bootstrap_message = (
        "FlatCAM could not load its startup interface.\n\n"
        "%s: %s\n\n"
        "Run setup_windows.ps1 again and review its dependency checks."
    ) % (type(bootstrap_import_error).__name__, str(bootstrap_import_error))
    if sys.platform == 'win32':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, bootstrap_message, "FlatCAM startup problem", 0x10)
        except Exception:
            print(bootstrap_message, file=sys.stderr)
    else:
        print(bootstrap_message, file=sys.stderr)
    sys.exit(1)

from multiprocessing import freeze_support

MIN_VERSION_MAJOR = 3
MIN_VERSION_MINOR = 6


def debug_trace():
    """
    Set a tracepoint in the Python debugger that works with Qt
    :return: None
    """
    from PyQt6.QtCore import pyqtRemoveInputHook
    # from pdb import set_trace
    pyqtRemoveInputHook()
    # set_trace()


def append_exception_log(log_file_path, exc_type, exc_value, exc_tb):
    msg = '%s\n' % str(datetime.today())
    msg += "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        with open(log_file_path, 'a') as log_file:
            log_file.write('\n' + msg)
    except IOError:
        pass
    return msg


def restart_flatcam(mode):
    settings = QSettings("Open Source", "FlatCAM_EVO")
    if mode == 'restart_2d':
        settings.setValue('startup_force_2d_once', True)
    elif mode == 'restart_safe_mode':
        settings.setValue('startup_safe_mode_once', True)
    settings.sync()
    subprocess.Popen([sys.executable] + sys.argv)


def splash_enabled(settings):
    headless = any(arg.replace(' ', '').lower() == '--headless=1' for arg in sys.argv[1:])
    return settings.value('splash_screen', True, type=bool) and not headless


if __name__ == '__main__':
    # All X11 calling should be thread safe otherwise we have strange issues
    # QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_X11InitThreads)
    # NOTE: Never talk to the GUI from threads! This is why I commented the above.
    freeze_support()
    app = QtWidgets.QApplication(sys.argv)

    portable = False
    # Folder for user settings.
    if sys.platform == 'win32':
        # #######################################################################################################
        # ####### CONFIG FILE WITH PARAMETERS REGARDING PORTABILITY #############################################
        # #######################################################################################################
        config_file = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + '\\config\\configuration.txt'
        try:
            with open(config_file, 'r'):
                pass
        except FileNotFoundError:
            config_file = os.path.dirname(os.path.realpath(__file__)) + '\\config\\configuration.txt'

        with open(config_file, 'r') as f:
            for line in f:
                param = str(line).replace('\n', '').rpartition('=')

                if param[0] == 'portable':
                    try:
                        portable = eval(param[2])
                    except NameError:
                        portable = False

        if portable is False:
            # data_path = shell.SHGetFolderPath(0, shellcon.CSIDL_APPDATA, None, 0) + '\\FlatCAM'
            data_path = os.path.join(os.getenv('appdata'), 'FlatCAM')
        else:
            data_path = os.path.dirname(os.path.dirname(os.path.realpath(__file__))) + '\\config'
    else:
        data_path = os.path.expanduser('~') + '/.FlatCAM'

    if not os.path.exists(data_path):
        os.makedirs(data_path)

    log_file_path = os.path.join(data_path, "log.txt")
    crash_log_path = os.path.join(data_path, "crash.log")
    crash_log_file = open(crash_log_path, 'a', buffering=1)
    faulthandler.enable(file=crash_log_file, all_threads=True)

    major_v = sys.version_info.major
    minor_v = sys.version_info.minor

    v_msg = "FlatCAM Evo uses PYTHON 3 or later. The version minimum is %s.%s\n"\
            "Your Python version is: %s.%s" % (MIN_VERSION_MAJOR, MIN_VERSION_MINOR, str(major_v), str(minor_v))

    # Supported Python version is >= 3.6
    if major_v < MIN_VERSION_MAJOR or (major_v >= MIN_VERSION_MAJOR and minor_v < MIN_VERSION_MINOR):
        print(v_msg)
        msg = '%s\n' % str(datetime.today())
        msg += v_msg

        try:
            with open(log_file_path) as f:
                log_file = f.read()
            log_file += '\n' + msg

            with open(log_file_path, 'w') as f:
                f.write(log_file)
        except IOError:
            with open(log_file_path, 'w') as f:
                f.write(msg)

        # if minor_v >= 8:
        #     os._exit(0)
        # else:
        #     sys.exit(0)
        sys.exit(0)

    def excepthook(exc_type, exc_value, exc_tb):
        if exc_type != KeyboardInterrupt:
            msg = append_exception_log(log_file_path, exc_type, exc_value, exc_tb)

            # show the message
            try:
                msgbox = QtWidgets.QMessageBox()
                displayed_msg = "The application encountered a critical error and it will close.\n"\
                                "A diagnostic report was saved to the FlatCAM log folder."
                title = "Critical Error"
                msgbox.setWindowTitle(title)  # taskbar still shows it
                ic = QtGui.QIcon()
                ic.addPixmap(QtGui.QPixmap("assets/resources/warning.png"), QtGui.QIcon.Mode.Normal)
                msgbox.setWindowIcon(ic)
                msgbox.setText('<b>%s</b>' % displayed_msg)
                msgbox.setDetailedText(msg)
                msgbox.setIcon(QtWidgets.QMessageBox.Icon.Critical)

                bt_yes = msgbox.addButton("Quit", QtWidgets.QMessageBox.ButtonRole.YesRole)
                msgbox.setDefaultButton(bt_yes)
                msgbox.exec()
            except Exception:
                QtWidgets.QApplication.quit()
        else:
            QtWidgets.QApplication.quit()
        # or QtWidgets.QApplication.exit(0)

    sys.excepthook = excepthook

    # apply style
    settings = QSettings("Open Source", "FlatCAM_EVO")
    if settings.contains("style"):
        style_index = settings.value('style', type=str)
        try:
            idx = int(style_index)
        except Exception:
            idx = 0
        style = QtWidgets.QStyleFactory.keys()[idx]
        app.setStyle(style)
    else:
        app.setStyle('windowsvista')

    if settings.contains("font_size"):
        font_size = int(settings.value("font_size", type=str))      # noqa
        font = QtGui.QFont()
        font.setPointSize(font_size)
        app.setFont(font)

    startup_splash = NullStartupSplash()
    if splash_enabled(settings):
        startup_splash = StartupSplashScreen(log_path=log_file_path)
        startup_splash.show()
        startup_splash.set_stage(
            'bootstrap',
            'Loading application modules',
            'Checking the Python environment and FlatCAM components.'
        )

    try:
        debug_trace()
        from appGUI import VisPyPatches
        VisPyPatches.apply_patches()
        from appMain import App
        startup_splash.set_version(App.version)
        fc = App(qapp=app, startup_splash=startup_splash)
    except Exception as startup_error:
        traceback_text = append_exception_log(
            log_file_path,
            type(startup_error),
            startup_error,
            startup_error.__traceback__
        )
        diagnostic = diagnose_startup_exception(
            startup_error,
            traceback_text,
            stage_id=startup_splash.current_stage,
            stage_title=startup_splash.current_stage_title
        )
        if isinstance(startup_splash, NullStartupSplash):
            startup_splash = StartupSplashScreen(log_path=log_file_path)
        action = startup_splash.show_failure(diagnostic, log_path=log_file_path)
        if action in ('restart_2d', 'restart_safe_mode'):
            try:
                restart_flatcam(action)
            except Exception as restart_error:
                QtWidgets.QMessageBox.critical(
                    startup_splash,
                    'FlatCAM restart failed',
                    'FlatCAM could not restart automatically.\n\n%s' % str(restart_error)
                )
        crash_log_file.close()
        sys.exit(1)

    # interrupt the Qt loop such that Python events have a chance to be responsive
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(100)

    try:
        sys.exit(app.exec())
    except SystemError:
        pass
    # app.exec()
