"""ADX-family input formats, independently implemented from public AquaMai docs.

See docs/ADX-PROTOCOL-NOTICE.md. No device I/O, calibration or firmware commands.
A USB identity is a candidate, never proof of a working channel.
"""
from dataclasses import dataclass
import base64

# profile, player; Maimoller player must be read from its feature report.
IDENTITIES = {
    (0x2e3c, 0x5750): ('adx-hid', 0), (0x2e4c, 0x5750): ('adx-hid', 1),
    (0x2e3c, 0x5767): ('adx-keyboard', 0), (0x2e3c, 0x5768): ('adx-keyboard', 1),
    (0x2e3c, 0x5751): ('npro-hid', 0), (0x2e3c, 0x5752): ('npro-hid', 1),
    (0x0e8f, 0x1224): ('maimoller-hid', None),
}
BUTTON_MAP = (5, 4, 3, 2, 9, 8, 7, 6)
TOUCH_MASK = (1 << 34) - 1


def report_layout(descriptor):
    """HID short/long items, globals Push/Pop, constant fields and Report IDs.

    Returns payload byte counts WITHOUT report ID. Reject malformed/unbounded
    descriptors; no length-only heuristics for unknown firmware collections.
    """
    if not isinstance(descriptor, bytes) or not 1 <= len(descriptor) <= 16384:
        raise ValueError('Invalid HID descriptor')
    at = 0; state = {'size': 0, 'count': 0, 'id': 0}; stack = []; bits = {}
    while at < len(descriptor):
        prefix = descriptor[at]; at += 1
        if prefix == 0xfe:
            if at + 2 > len(descriptor): raise ValueError('Truncated long item')
            size = descriptor[at]; at += 2
            if at + size > len(descriptor): raise ValueError('Truncated long item')
            at += size; continue
        size = (0, 1, 2, 4)[prefix & 3]
        if at + size > len(descriptor): raise ValueError('Truncated short item')
        value = int.from_bytes(descriptor[at:at + size], 'little'); at += size
        kind = (prefix >> 2) & 3; tag = prefix >> 4
        if kind == 1:
            if tag in (7, 8, 9):
                key = {7: 'size', 8: 'id', 9: 'count'}[tag]
                if (tag == 8 and not 1 <= value <= 255) or value > 65536:
                    raise ValueError('Invalid HID globals')
                state[key] = value
            elif tag == 10:
                if len(stack) >= 16: raise ValueError('HID global stack overflow')
                stack.append(state.copy())
            elif tag == 11:
                if not stack: raise ValueError('HID global stack underflow')
                state = stack.pop()
        elif kind == 0 and tag in (8, 9, 11):
            key = ({8: 'input', 9: 'output', 11: 'feature'}[tag], state['id'])
            count = state['size'] * state['count']
            if count <= 0 or bits.get(key, 0) + count > 8192:
                raise ValueError('Invalid HID report size')
            bits[key] = bits.get(key, 0) + count
    if stack: raise ValueError('Unbalanced HID globals')
    if any(report_id for _, report_id in bits) and any(report_id == 0 for _, report_id in bits):
        raise ValueError('Mixed numbered and unnumbered HID reports')
    return {key: (value + 7) // 8 for key, value in bits.items()}


def normalize(layout, kind, report_id, data):
    expected = layout.get((kind, report_id))
    if expected is None: raise ValueError('Unexpected HID report ID')
    # IOHID callbacks can supply the ID in the buffer or separately. The
    # descriptor resolves this unambiguously, including unnumbered reports.
    if len(data) == expected:
        return data
    if len(data) == expected + 1 and data[0] == report_id:
        return data[1:]
    raise ValueError('HID report length does not match descriptor')


@dataclass(frozen=True)
class InputState:
    touch: int = 0
    buttons: int = 0  # bit0..7 = physical outer button1..8
    auxiliary: int = 0  # select1, select2, service, test, coin


def decode(profile, payload, report_id=0, player=0):
    if profile == 'adx-hid':
        canonical = bytes([report_id]) + payload
        if not 14 <= len(canonical) <= 65: raise ValueError('ADX input too short')
        buttons = sum((canonical[source] == 1) << index for index, source in enumerate(BUTTON_MAP))
        # Factory defaults: Select1P, Service, Select2P, Test.
        aux = sum((canonical[source] == 1) << target for source, target in ((10, 0), (11, 2), (12, 1), (13, 3)))
        return InputState(buttons=buttons, auxiliary=aux)
    if profile == 'npro-hid':
        if len(payload) != 8: raise ValueError('Invalid NPro input')
        buttons = payload[6]  #bit0..7 correspond to outer buttons1..8.
        raw_aux = payload[7]
        aux = sum(bool(raw_aux & (1 << source)) << target for source, target in ((0, 0), (1, 2), (2, 1), (3, 3)))
        return InputState(int.from_bytes(payload[:6], 'little') & TOUCH_MASK, buttons, aux)
    if profile == 'maimoller-hid':
        if len(payload) != 7: raise ValueError('Invalid Maimoller input')
        touch = payload[0] | payload[1] << 8 | (payload[2] & 3) << 16 | payload[3] << 18 | payload[4] << 26
        raw_aux = payload[6]
        aux = ((raw_aux & 1) << 4) | (raw_aux & 2) << 1 | (raw_aux & 4) << 1 | ((raw_aux >> 3) & 1) << player
        return InputState(touch, payload[5], aux)
    raise ValueError('No custom input decoder for this profile')


def endpoint(row):
    identity = IDENTITIES.get((row.get('vendor'), row.get('product')))
    if identity is None: return None
    profile, player = identity
    result = dict(id=str(row['id']), profile=profile, player=player, name=row.get('name', profile),
                  vendor=row['vendor'], product=row['product'], status='unverified',
                  channels=[], detail='等待实机验证')
    # Never capture the standard keyboard/mouse collection, even on a known VID.
    if (row.get('usagePage') == 1 and row.get('usage') in (1, 2, 6, 7)) or row.get('usagePage') == 7:
        result.update(status='keyboard', detail='系统键盘接口'); return result
    if profile == 'adx-keyboard':
        result.update(status='keyboard', detail='此固件使用系统键盘输入'); return result
    try:
        descriptor = base64.b64decode(row.get('descriptor', ''), validate=True)
        layout = report_layout(descriptor)
        expected = {'adx-hid': range(13, 65), 'npro-hid': (8,), 'maimoller-hid': (7,)}[profile]
        reports = [rid for (kind, rid), length in layout.items() if kind == 'input' and length in expected]
        if len(reports) != 1: raise ValueError('Ambiguous or unknown report layout')
        result.update(status='candidate', channels=['buttons'] + ([] if profile == 'adx-hid' else ['touch']),
                      reportID=reports[0], descriptor=row['descriptor'], detail='已匹配输入协议；尚未实机验证')
    except (ValueError, TypeError):
        result.update(status='unsupported', detail='报告格式未匹配，保留系统键盘输入')
    return result


def select_endpoints(rows):
    devices = [value for row in rows if (value := endpoint(row)) is not None]
    # Never silently pick one of multiple collections/controllers for a player.
    for player in (0, 1):
        candidates = [d for d in devices if d['status'] == 'candidate' and d['player'] == player]
        if len(candidates) > 1:
            for d in candidates: d.update(status='ambiguous', detail='同一玩家有多个输入接口，请只保留一台')
    return devices
