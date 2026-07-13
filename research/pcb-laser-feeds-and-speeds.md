# PCB and 10 W Diode Laser Feeds and Speeds

Research date: 2026-07-12

## Scope

This document proposes conservative factory starting points for common
1/8-inch-shank PCB tools and a nominal 10 W blue diode laser. These are not
universal optimum settings. Machine rigidity, spindle runout, actual cutter
geometry, workholding, substrate, laser focus, air assist, and controller
configuration all affect the result.

The 1/8-inch dimension on most PCB tooling is the shank diameter. Presets must
be named and matched by the actual cutting diameter or V-tip geometry, not just
by the shank.

## PCB milling recommendations

The following metric values are suitable as conservative starting presets for
a hobby-class machine with a spindle capable of approximately 10,000 to
12,000 RPM.

| Operation | Tool | XY feed | Z feed | Depth per pass | RPM |
| --- | --- | ---: | ---: | ---: | ---: |
| FR-4 isolation | 30 degree V-bit, 0.10 mm tip | 120 mm/min | 30 mm/min | 0.08 mm | 12,000 |
| FR-4 isolation | FoxAlien 60 degree V-bit, 0.10 mm tip, 1/8 inch shank | 120 mm/min | 30 mm/min | 0.08 mm | 12,000 |
| FR-4 fine milling | 0.4 mm flat end mill | 120 mm/min | 12 mm/min | 0.05 mm | 12,000 |
| FR-4 milling | 0.8 mm flat end mill | 180 mm/min | 20 mm/min | 0.10 mm | 12,000 |
| FR-4 milling | 1.0 mm flat end mill | 200 mm/min | 25 mm/min | 0.10 mm | 12,000 |
| FR-4 milling | 1.6 mm flat end mill | 240 mm/min | 30 mm/min | 0.13 mm | 12,000 |
| FR-4 clearing or cutout | 3.175 mm flat end mill | 300 mm/min | 30 mm/min | 0.13 mm | 12,000 |

Bantam Tools publishes 12,000 RPM, 360 mm/min feed, and 30 mm/min
plunge as its conservative FR-1 settings for 1/32 through 1/8-inch flat end
mills. Its more aggressive settings reach 1,500 mm/min, but assume suitable
machine rigidity, workholding, and spindle capability and should not be
generic factory defaults.

The FR-4 values above are deliberately conservative inferences from the
Bantam FR-1 baselines and PreciseBits FR-4 application data rather than direct
manufacturer recipes for a particular hobby router. V-bit cut depth controls
the effective isolation width, so surface mapping and a flat workpiece are
more important than increasing feed rate.

### PCB drill starting points

| Drill diameter | Z feed | RPM |
| ---: | ---: | ---: |
| 0.5 to 0.7 mm | 60 mm/min | 12,000 |
| 0.8 to 1.0 mm | 80 mm/min | 12,000 |
| 1.1 to 1.5 mm | 100 mm/min | 12,000 |
| 1.6 to 2.0 mm | 120 mm/min | 12,000 |
| 2.1 to 3.175 mm | 150 mm/min | 12,000 |

These drill values are conservative hobby-spindle starting points, not direct
copies of industrial PCB drill data. PreciseBits publishes values for premium
carbide PCB drills at speeds as high as 80,000 RPM and warns against blindly
extending them to other drills or substrates. Low-speed hobby spindles,
runout, and inexpensive bits require testing. Pecking or shallow multi-depth
drilling can improve chip evacuation when the controller and toolpath support
it.

FR-4 is substantially more abrasive than FR-1, so the seed database contains
only explicitly labeled conservative FR-4 profiles. Fine composite dust
requires source extraction or enclosure; avoid blowing it around the
workspace.

The FoxAlien profile matches ASIN B08881PKBN: a triangular tungsten-carbide
V-bit with nano-blue coating, 60 degree included angle, 0.1 mm cutting edge,
and 1/8-inch (3.175 mm) shank. The listing identifies PCB as a supported
application but does not publish FR-4 feeds and speeds, so the conservative
FR-4 values remain derived from the machining sources above.

## 10 W blue diode laser recommendations

The following values are manufacturer-published xTool D1 10 W starting points.
They should be treated as the center of a material-test grid, not guaranteed
recipes for every nominal 10 W module.

| Material and operation | Feed | Power | Passes |
| --- | ---: | ---: | ---: |
| Basswood engraving | 6,000 mm/min | 75% | 1 |
| 3 mm basswood cutting | 300 mm/min | 100% | 1 |
| 4 mm basswood cutting | 180 mm/min | 100% | 1 |
| 5 mm basswood cutting | 120 mm/min | 100% | 1 |
| Corrugated card engraving | 6,000 mm/min | 40% | 1 |
| 3.5 mm corrugated card cutting | 540 mm/min | 100% | 1 |
| Coated metal engraving | 4,200 mm/min | 100% | 1 |
| Stainless steel marking | 720 mm/min | 100% | 1 |

FlatCAM's GRBL laser preprocessors emit laser power through the spindle-speed
`S` word. Percent power therefore depends on the controller's `$30` maximum:

| Power | `$30=1000` | `$30=255` |
| ---: | ---: | ---: |
| 40% | `S400` | `S102` |
| 75% | `S750` | `S191` |
| 100% | `S1000` | `S255` |

Factory presets should state the assumed `$30` scale in their names or
metadata. For GRBL, `M4` dynamic laser power is normally preferable for
engraving because output follows actual motion speed. Cutting behavior must be
validated on the target controller.

Run a speed/power material test for each material batch. Laser output, spot
size, focus, acceleration, air assist, wood glue, density, and moisture can all
change the result. Clear acrylic generally cannot be processed directly by a
blue diode laser.

Do not include presets for artificial leather or unknown plastics. PVC, vinyl,
and other chlorine-containing materials can generate dangerous corrosive
fumes. Use appropriate eye protection and ventilation, keep fire suppression
equipment nearby, and never operate a laser unattended.

## Seed database implementation assessment

Implementation is feasible, with the following design:

1. Ship a version-controlled factory seed definition in the repository.
2. When `tools_db_<version>.FlatDB` does not exist, populate the new per-user
   database from the seed instead of writing `{}`.
3. Never replace or merge over an existing user database automatically.
4. Build complete records from FlatCAM defaults and overlay only the preset
   fields, avoiding brittle hand-maintained copies of every schema field.
5. Add tests for first-run seeding, preservation of an existing database,
   valid target/tool-shape values, and power scaling.

### Information or decisions still needed

- **Units:** the current `.FlatDB` format has no unit metadata and no observed
  unit conversion on load. Decide whether factory data is always metric,
  whether first-run seeding converts from canonical metric into the active
  application units, or whether the file format gains explicit unit metadata.
  Unit-aware first-run conversion is the least disruptive choice.
- **Laser power scale:** select a default GRBL `$30` convention. `1000` is a
  practical default, but the preset names must expose that assumption unless
  FlatCAM adds a controller power-scale setting.
- **Laser recipe model:** the tool database stores feed, `S` power, laser-on
  command, and preprocessor, but it does not cleanly model material thickness
  and pass count as a complete laser recipe. Initial laser entries can still be
  useful, but a dedicated material-preset model would be more accurate.
- **FR-4 baseline:** the initial seed uses explicitly labeled, conservative
  FR-4 entries and does not include FR-1 profiles.

The selected defaults are canonical metric source data converted on first run,
GRBL `$30=1000`, conservative FR-4 PCB presets, and laser entries labeled as
test-grid starting points.

## Sources

- [Bantam Tools: FR-1 PCB blanks and recommended feeds and speeds](https://support.bantamtools.com/hc/en-us/articles/115001671734-FR-1-PCB-Blanks)
- [FoxAlien 60 degree, 0.1 mm V-bit (ASIN B08881PKBN)](https://www.amazon.com/dp/B08881PKBN)
- [Bantam Tools: engraving-bit isolation milling](https://support.bantamtools.com/hc/en-us/articles/115001656913-Engraving-Bit-Isolation-Milling)
- [PreciseBits: carbide PCB drill feeds and speeds](https://www.precisebits.com/reference/drillfeedspeed.htm)
- [PreciseBits: V-tip engraving and PCB trace-isolation application data](https://www.precisebits.com/products/carbidebits/scoreengrave.asp)
- [PreciseBits: calibrating feeds and speeds for carbide microtools](https://www.precisebits.com/tutorials/calibrating_feeds_n_speeds.htm)
- [xTool: D1 10 W recommended material parameters](https://support.xtool.com/article/518)
- [xTool: laser chemical safety](https://support.xtool.com/article/34?from=xTool)
- [LightBurn: Material Test](https://docs.lightburnsoftware.com/latest/Reference/MaterialTest/)
- [LightBurn: job and fire safety](https://docs.lightburnsoftware.com/latest/GetStarted/JobControl/)
- [OSHA: advanced composite machining dust](https://www.osha.gov/otm/section-3-health-hazards/chapter-1)
