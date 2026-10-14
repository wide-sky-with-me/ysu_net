"""Shared account presentation; preserve portal units and distinguish missing values."""
import re
import unicodedata
from html.parser import HTMLParser

from .common import QueryError, online_state


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('br', 'p', 'div', 'li'):
            self.parts.append(' ')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.hidden = max(0, self.hidden - 1)
        if tag in ('p', 'div', 'li'):
            self.parts.append(' ')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def _text(value):
    if value is None or isinstance(value, (bool, dict, list)):
        return ''
    parser = _PlainText()
    parser.feed(str(value))
    parser.close()
    text = re.sub(r'\x1b\].*?(?:\x07|\x1b\\)', '', ''.join(parser.parts), flags=re.S)
    text = re.sub(r'\x1b\[[0-?]*[ -/]*[@-~]', '', text)
    cleaned = ''.join(
        ' ' if char.isspace() else char
        for char in text
        if char.isspace() or not unicodedata.category(char).startswith('C')
    )
    return ' '.join(cleaned.split())


def summarize_account_payload(payload):
    inner = {}
    current = payload
    # Some portals wrap accountInfo in data.data; absent outer keys are not a leaf.
    for _ in range(6):
        if not isinstance(current, dict):
            break
        if isinstance(current.get('accountInfo'), list):
            inner = current
            break
        if 'name' in current or 'service' in current:
            inner = current
        current = current.get('data')
    items = {}
    raw_items = inner.get('accountInfo')
    for item in raw_items if isinstance(raw_items, list) else []:
        if not isinstance(item, dict):
            continue
        title = _text(item.get('title'))
        if title:
            items[title] = {'content': item.get('content'), 'link': item.get('link')}
    return {'name': inner.get('name'), 'service': inner.get('service'), 'items_map': items}


def format_account_info(online_info, account_payload):
    try:
        online = online_state(online_info)
    except (QueryError, TypeError, AttributeError):
        return '网络状态：未知，暂未取得有效账户信息。'
    if not online:
        return '网络状态：离线\n账户信息：请先运行 ysu login 或 ysu on，再使用 ysu info 查询。'
    fields = online_info['data']['portalOnlineUserInfo']
    account = summarize_account_payload(account_payload)
    lines = ['网络状态：在线']
    for title, value in (
        ('用户', account.get('name') or fields.get('userName')),
        ('账号', fields.get('userId') or fields.get('userName')),
        ('IP', fields.get('userIp')),
        ('SSID', fields.get('ssid')),
        ('当前服务', fields.get('realServiceName') or fields.get('service') or account.get('service')),
    ):
        text = _text(value)
        if text:
            lines.append(f'{title}：{text}')
    items = account['items_map']
    remaining = False
    balance = False
    for title, item in items.items():
        content = _text(item.get('content'))
        if not content:
            continue
        # Display portal-authored account items without exposing their signed links.
        lines.append(f'{title.replace("套餐&余额", "套餐与余额")}：{content}')
        remaining |= '剩余流量' in title
        balance |= '余额' in title
    if not remaining:
        lines.append('剩余流量：门户未提供（不代表 0 或不限量）')
    if not balance:
        lines.append('套餐与余额：门户未提供')
    if not remaining or not balance:
        lines.append('提示：可在校园网门户的业务明细或运营商自助服务中进一步查询。')
    lines.append('说明：流量和余额按门户原文展示，不推算额度或换算未知单位。')
    return '\n'.join(lines)


def account_summary(online_info, account_payload):
    """Structured variant of format_account_info for graphical front ends."""
    try:
        online = online_state(online_info)
    except (QueryError, TypeError, AttributeError):
        return None
    if not online:
        return {'online': False, 'fields': [], 'items': []}
    info = online_info['data']['portalOnlineUserInfo']
    account = summarize_account_payload(account_payload)
    fields = []
    for title, value in (
        ('用户', account.get('name') or info.get('userName')),
        ('账号', info.get('userId') or info.get('userName')),
        ('IP', info.get('userIp')),
        ('SSID', info.get('ssid')),
        ('当前服务', info.get('realServiceName') or info.get('service') or account.get('service')),
    ):
        text = _text(value)
        if text:
            fields.append((title, text))
    items = [(title.replace('套餐&余额', '套餐与余额'), content)
             for title, item in account['items_map'].items()
             if (content := _text(item.get('content')))]
    return {'online': True, 'fields': fields, 'items': items}
