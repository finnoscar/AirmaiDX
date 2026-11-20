"""Author the approved notebook and controller as editable Icon Composer layers."""
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]
ICON = ROOT / 'Resources/AppIcon.icon'
ASSETS = ICON / 'Assets'


def rounded_rectangle(x, y, width, height, radius):
    return (f'M{x + radius} {y} H{x + width - radius} '
            f'Q{x + width} {y} {x + width} {y + radius} '
            f'V{y + height - radius} Q{x + width} {y + height} {x + width - radius} {y + height} '
            f'H{x + radius} Q{x} {y + height} {x} {y + height - radius} '
            f'V{y + radius} Q{x} {y} {x + radius} {y} Z')


def ring(x, y, width, height, radius, thickness):
    return (rounded_rectangle(x, y, width, height, radius) + ' ' +
            rounded_rectangle(x + thickness, y + thickness, width - thickness * 2,
                              height - thickness * 2, radius - thickness))


def svg(name, paths):
    # All sources share the same full canvas and registration coordinates.
    (ASSETS / name).write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" '
        'viewBox="0 0 1024 1024"><g transform="scale(0.816587)" '
        'fill="#008dff" fill-rule="evenodd">' + paths + '</g></svg>\n')


def path(data):
    return f'<path d="{data}"/>'


def color(value):
    return 'srgb:' + ','.join(f'{int(value[i:i + 2], 16) / 255:.5f}' for i in (0, 2, 4)) + ',1.00000'


def layer(name, image, light, dark, mono):
    return {'name': name, 'image-name': image, 'glass': False,
            'fill-specializations': [
                {'value': {'solid': color(light)}},
                {'appearance': 'dark', 'value': {'solid': color(dark)}},
                {'appearance': 'tinted', 'value': {'solid': f'extended-gray:{mono},1.00000'}}]}


def group(name, layers):
    return {'name': name, 'layers': layers, 'lighting': 'individual',
            'specular': False, 'blur-material': 0,
            'shadow': {'kind': 'neutral', 'opacity': 0.08},
            'translucency': {'enabled': False, 'value': 0}}


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    svg('01-Notebook-Surface.svg', path(rounded_rectangle(153, 310, 735, 471, 57)) +
        path(rounded_rectangle(121, 740, 798, 66, 33)))
    # The capsule and finger recess share the full screen's center at x=520.5.
    frame = ('M153 740 V367 Q153 310 210 310 H831 Q888 310 888 367 V740 H863 '
             'V367 Q863 335 831 335 H210 Q178 335 178 367 V740 Z')
    base = ('M154 740 H475.5 Q481.5 740 487.5 746 Q490.5 749 498.5 749 '
            'H542.5 Q550.5 749 553.5 746 Q559.5 740 565.5 740 H886 '
            'Q919 740 919 773 Q919 806 886 806 H154 Q121 806 121 773 Q121 740 154 740 Z '
            + rounded_rectangle(144, 762, 752, 21, 10.5))
    svg('02-Notebook-Outline.svg', path(frame) + path(base) +
        path(rounded_rectangle(486.5, 356, 68, 22, 11)))
    svg('03-Controller-Surface.svg', path(rounded_rectangle(593, 423, 462, 613, 89)))
    svg('04-Controller-Outline.svg', path(ring(593, 423, 462, 613, 89, 25)))
    controls = path(ring(666, 478, 317, 121, 30, 18))
    controls += path('M955 801 A131 131 0 1 0 693 801 A131 131 0 1 0 955 801 Z '
                     'M937 801 A113 113 0 1 0 711 801 A113 113 0 1 0 937 801 Z')
    # Eight filled, round-ended annular keys, with no strokes or raster effects.
    keys = []
    for index in range(8):
        angle = -math.pi / 2 + index * math.pi / 4
        half_span = 0.18
        def point(radius, offset):
            return f'{824 + radius * math.cos(angle + offset):.3f} {801 + radius * math.sin(angle + offset):.3f}'
        keys.append(path(f'M{point(188, -half_span)} A188 188 0 0 1 {point(188, half_span)} '
                         f'A19 19 0 0 1 {point(150, half_span)} '
                         f'A150 150 0 0 0 {point(150, -half_span)} '
                         f'A19 19 0 0 1 {point(188, -half_span)} Z'))
    svg('05-Controller-Controls.svg', controls + ''.join(keys))
    document = {
        'fill-specializations': [
            {'value': {'linear-gradient': [color('f4f6fc'), color('dce4f5')]}},
            {'appearance': 'dark', 'value': {'linear-gradient': [color('263344'), color('151e2c')]}},
            {'appearance': 'tinted', 'value': 'automatic'}],
        # Icon Composer stores groups and layers from front to back.
        'groups': [
            group('02 Controller', [
                layer('Controls', '05-Controller-Controls.svg', '008dff', '65b9ff', 0.95),
                layer('Enclosure', '04-Controller-Outline.svg', '008dff', '65b9ff', 0.95),
                layer('Surface', '03-Controller-Surface.svg', 'd5ebff', '233e59', 0.34)]),
            group('01 Notebook', [
                layer('Frame, capsule and recess', '02-Notebook-Outline.svg', '008dff', '65b9ff', 0.95),
                layer('Surface', '01-Notebook-Surface.svg', 'cee6fb', '20384e', 0.25)])],
        'supported-platforms': {'squares': 'shared'}
    }
    (ICON / 'icon.json').write_text(json.dumps(document, indent=2) + '\n')
    print(ICON)


if __name__ == '__main__':
    main()
