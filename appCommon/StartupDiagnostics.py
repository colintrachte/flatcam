from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StartupWarning:
    title: str
    detail: str
    suggestion: str


@dataclass(frozen=True)
class StartupDiagnostic:
    stage_id: str
    stage_title: str
    summary: str
    likely_cause: str
    explanation: str
    recommended_action: str
    recovery_action: str
    technical_details: str
    missing_module: Optional[str] = None

    def as_text(self) -> str:
        lines = [
            "FlatCAM startup diagnostic",
            "Stage: %s" % self.stage_title,
            "Summary: %s" % self.summary,
            "Likely cause: %s" % self.likely_cause,
            "Recommended action: %s" % self.recommended_action,
            "",
            self.technical_details.strip()
        ]
        return "\n".join(lines).strip() + "\n"


def diagnose_startup_exception(
        exc: BaseException,
        traceback_text: str,
        stage_id: str = "bootstrap",
        stage_title: str = "Loading application modules"
) -> StartupDiagnostic:
    message = "%s: %s" % (type(exc).__name__, str(exc))
    evidence = "%s\n%s" % (message, traceback_text)
    searchable = evidence.lower()
    stage_searchable = "%s %s" % (stage_id.lower(), stage_title.lower())

    if any(token in stage_searchable or token in searchable for token in (
            "canvas", "graphics", "renderer", "opengl", "vispy", "gl context")):
        return StartupDiagnostic(
            stage_id=stage_id,
            stage_title=stage_title,
            summary="The graphics canvas could not be initialized.",
            likely_cause="The OpenGL renderer could not create a usable graphics context.",
            explanation=(
                "Preferences and project data are not changed by this failure. "
                "FlatCAM can retry with its software-friendly 2D compatibility renderer."
            ),
            recommended_action="Restart FlatCAM in 2D compatibility mode.",
            recovery_action="restart_2d",
            technical_details=evidence
        )

    missing_module = getattr(exc, "name", None)
    if isinstance(exc, (ImportError, ModuleNotFoundError)) or "no module named" in searchable:
        module_label = missing_module or "a required Python package"
        return StartupDiagnostic(
            stage_id=stage_id,
            stage_title=stage_title,
            summary="A Python dependency could not be loaded.",
            likely_cause="The installed environment is missing or cannot import %s." % module_label,
            explanation=(
                "This usually means setup did not finish, a package installation is damaged, "
                "or FlatCAM was launched with a different Python environment."
            ),
            recommended_action="Review the diagnostic report and rerun the project setup script.",
            recovery_action="copy_diagnostics",
            technical_details=evidence,
            missing_module=missing_module
        )

    if any(token in stage_searchable or token in searchable for token in (
            "preprocessor", "plugin", "flatcampostprocessor")):
        return StartupDiagnostic(
            stage_id=stage_id,
            stage_title=stage_title,
            summary="A custom manufacturing component failed while loading.",
            likely_cause="A user preprocessor or plugin is incompatible or contains an error.",
            explanation=(
                "Safe mode skips user preprocessors for one launch so the failing component can "
                "be identified without changing project files."
            ),
            recommended_action="Restart once in safe mode.",
            recovery_action="restart_safe_mode",
            technical_details=evidence
        )

    if any(token in stage_searchable or token in searchable for token in (
            "preference", "defaults", "flatconfig", "jsondecode", "json")):
        return StartupDiagnostic(
            stage_id=stage_id,
            stage_title=stage_title,
            summary="FlatCAM could not read its saved configuration.",
            likely_cause="A preferences file is incomplete, corrupt, or inaccessible.",
            explanation=(
                "The diagnostic log identifies the affected file. Preserve it before resetting "
                "preferences so settings can be recovered if needed."
            ),
            recommended_action="Open the log folder and inspect the named configuration file.",
            recovery_action="open_log",
            technical_details=evidence
        )

    if any(token in stage_searchable or token in searchable for token in (
            "language", "translation", "gettext", "locale")):
        return StartupDiagnostic(
            stage_id=stage_id,
            stage_title=stage_title,
            summary="Language resources could not be loaded.",
            likely_cause="Translation files are missing, unreadable, or do not match this build.",
            explanation="The installation may be incomplete even though user project files are unaffected.",
            recommended_action="Copy the diagnostic report and repair or reinstall FlatCAM.",
            recovery_action="copy_diagnostics",
            technical_details=evidence
        )

    return StartupDiagnostic(
        stage_id=stage_id,
        stage_title=stage_title,
        summary="FlatCAM stopped during startup before the workspace was ready.",
        likely_cause="FlatCAM could not determine an exact cause from this exception alone.",
        explanation=(
            "The failed stage and complete traceback have been preserved. No automatic repair "
            "will be attempted without stronger evidence."
        ),
        recommended_action="Copy the diagnostic report or open the log folder for review.",
        recovery_action="copy_diagnostics",
        technical_details=evidence
    )
