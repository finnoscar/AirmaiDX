"""Local identifier validation; never invent or reformat service credentials."""
import configparser
import re

from launch_guidance import LaunchRequirement
from storage import ini_set, serialized

SEGATOOLS = 'segatools.ini'
KEYCHIP_FORMAT = '请原样填写服务方提供的 Key Chip，最多 16 位英文字母、数字或连字符。'


def validate_keychip(value):
    # Segatools' nusec_config stores 16 bytes. A single observed long-form
    # serial pattern is not an exhaustive list of service-issued identifiers.
    identifier = value.strip() if isinstance(value, str) else ''
    if (not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,15}', identifier)
            or identifier.lower() in {'none', 'null', 'unset', 'default', 'changeme', 'invalid'}
            or not identifier.strip('0-')):
        raise ValueError(KEYCHIP_FORMAT)
    return identifier


def parse_keychip(text):
    parser = configparser.ConfigParser(strict=False, interpolation=None, default_section='\0')
    try:
        parser.read_string(text)
        sections = [section for section in parser.sections() if section.lower() == 'keychip']
        if len(sections) > 1:
            raise ValueError()
    except (configparser.Error, ValueError):
        # Parse exceptions can include entire lines of the INI, including IDs.
        raise LaunchRequirement('machineConfig', 'segatools.ini 的格式有误，请在「机台配置」中检查或从备份恢复。') from None
    return parser.get(sections[0], 'id', fallback='').strip() if sections else ''


def require_keychip(store, game):
    try:
        config = store.read_config(game['id'], SEGATOOLS)
    except (OSError, ValueError):
        raise LaunchRequirement('machineConfig', '无法读取 segatools.ini。请确认 HDD 中有这份文件，或在「诊断与恢复」中查看备份。') from None
    value = parse_keychip(config['text'])
    if not value:
        raise LaunchRequirement('keychipMissing', '这个 HDD 还没有填写 Key Chip。')
    try:
        validate_keychip(value)
    except ValueError:
        raise LaunchRequirement('keychipInvalid', '这个 HDD 的 Key Chip 是占位值或格式不正确。') from None


@serialized
def save_keychip(store, game_id, value):
    identifier = validate_keychip(value)
    config = store.read_config(game_id, SEGATOOLS)
    parse_keychip(config['text'])
    original = config['text']
    normalized = original.replace('\r\n', '\n')
    body = normalized.rstrip('\n')
    text = ini_set(body, 'keychip', 'id', identifier) + normalized[len(body):]
    if '\r\n' in original:
        text = text.replace('\n', '\r\n')
    if parse_keychip(text) != identifier:
        raise LaunchRequirement('machineConfig', 'segatools.ini 的格式有误，请在「机台配置」中检查或从备份恢复。')
    store.save_config(game_id, SEGATOOLS, text, config['sha256'], config['encoding'])
    return True
