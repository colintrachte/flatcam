# ##########################################################
# FlatCAM: 2D Post-processing for Manufacturing            #
# http://flatcam.org                                       #
# MIT Licence                                              #
# ##########################################################

from preprocessors.Repetier import Repetier


class Klipper(Repetier):

    def start_code(self, p):
        if str(p.units).upper() != 'MM':
            raise ValueError('The Klipper preprocessor supports metric (MM) projects only.')

        gcode = super().start_code(p)
        gcode = gcode.replace(
            ';This preprocessor is used with a motion controller loaded with REPETIER firmware.',
            ';This preprocessor is used with a motion controller loaded with KLIPPER firmware.\n'
            ';Tool changes require [pause_resume] in the Klipper configuration.\n'
            ';M106/M107 spindle control requires [fan] in the Klipper configuration.'
        )

        # Klipper uses millimeters and feed-per-minute internally and does not
        # implement the corresponding modal G20/G21 and G94 commands.
        lines = [line for line in gcode.splitlines() if line not in {'G21', 'G94'}]
        return '\n'.join(lines) + '\n'

    def toolchange_code(self, p):
        lines = []
        for line in super().toolchange_code(p).splitlines():
            if line.strip() == 'M84':
                # Keep the axes energized so Klipper retains the homed state.
                continue
            if line.startswith('@pause '):
                lines.append('; ' + line[len('@pause '):])
                lines.append('PAUSE')
                continue
            lines.append(line)
        return '\n'.join(lines) + '\n'

    def spindle_code(self, p):
        if p.spindlespeed is None:
            return 'M106'

        pwm = max(0, min(255, int(round(p.spindlespeed))))
        return 'M106 S%d' % pwm
