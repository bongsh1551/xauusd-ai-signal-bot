import io
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
import requests


def fetch_chart(key, interval, minutes, now):
    response = requests.get(
        'https://api.twelvedata.com/time_series',
        params={'symbol': 'XAU/USD', 'interval': interval,
                'outputsize': 160, 'timezone': 'UTC', 'apikey': key},
        timeout=(10, 45),
    )
    if response.status_code != 200:
        raise RuntimeError(f'{interval}: data HTTP {response.status_code}')
    data = response.json()
    if data.get('status') != 'ok' or not data.get('values'):
        raise RuntimeError(f'{interval}: data rejected; code={data.get("code", "unknown")}')
    meta = data.get('meta', {})
    if meta.get('symbol') != 'XAU/USD' or meta.get('interval') != interval:
        raise RuntimeError(f'{interval}: unexpected symbol or interval')
    frame = pd.DataFrame(data['values'])
    frame.index = pd.to_datetime(frame.pop('datetime'), utc=True, errors='raise')
    if frame.index.has_duplicates or frame.index.isna().any():
        raise RuntimeError(f'{interval}: invalid or duplicate timestamps')
    frame = frame[['open', 'high', 'low', 'close']].apply(pd.to_numeric, errors='raise')
    frame.columns = ['Open', 'High', 'Low', 'Close']
    frame = frame.sort_index()
    if not frame.map(lambda x: pd.notna(x) and 0 < x < float('inf')).all().all():
        raise RuntimeError(f'{interval}: invalid prices')
    if ((frame.High < frame[['Open', 'Close', 'Low']].max(axis=1)) |
            (frame.Low > frame[['Open', 'Close', 'High']].min(axis=1))).any():
        raise RuntimeError(f'{interval}: invalid OHLC ordering')
    if frame.index.max() > now + pd.Timedelta(seconds=60):
        raise RuntimeError(f'{interval}: future timestamp; stop for timezone verification')
    frame = frame[frame.index + pd.Timedelta(minutes=minutes) <= now]
    if len(frame) < 50:
        raise RuntimeError(f'{interval}: insufficient closed candles')
    last_open = frame.index[-1]
    age = (now - (last_open + pd.Timedelta(minutes=minutes))).total_seconds() / 60
    stale = age > max(15, minutes * 2)
    label = 'HISTORICAL / STALE - TEST ONLY' if stale else 'CHART TEST ONLY - NOT A SIGNAL'
    plot_frame = frame.tail(120).copy()
    plot_frame.index = plot_frame.index.tz_convert('Asia/Kuala_Lumpur').tz_localize(None)
    buffer = io.BytesIO()
    fig, _ = mpf.plot(
        plot_frame, type='candle', style='yahoo', volume=False,
        title=f'XAU/USD {interval} | MYT UTC+8\n{label}',
        ylabel='USD per oz', datetime_format='%m-%d %H:%M',
        figsize=(14, 7), returnfig=True, tight_layout=True,
    )
    try:
        fig.savefig(buffer, format='png', dpi=130, bbox_inches='tight')
    finally:
        plt.close(fig)
    buffer.seek(0)
    last_myt = last_open.tz_convert('Asia/Kuala_Lumpur').strftime('%Y-%m-%d %H:%M')
    gaps = int((frame.index.to_series().diff() > pd.Timedelta(minutes=minutes)).sum())
    caption = (
        f'🧪 XAU/USD {interval} 画图测试\n'
        f'最后已收线 K 线起点（大马时间）：{last_myt}\n'
        f'距该根收线：{age:.1f} 分钟\n'
        f'数据状态：{"历史/陈旧数据，仅作画图测试" if stale else "通过本次时间阈值检查，未验证实时报价"}\n'
        f'样本内时间缺口：{gaps}（可能含休市，尚未判定原因）\n'
        '来源：Twelve Data；不等于你的券商报价。\n'
        '本图仅测试，不是交易信号；未调用 AI，禁止据此入场。'
    )
    return interval, buffer, caption


def main():
    if os.getenv('GITHUB_EVENT_NAME') != 'workflow_dispatch':
        print('测试阶段：跳过定时任务。')
        return
    names = ['TWELVEDATA_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    config = {name: os.getenv(name, '').strip() for name in names}
    if any(not config[name] for name in names):
        print('缺少必要 Secret；请检查配置。')
        sys.exit(1)
    try:
        now = pd.Timestamp.now(tz='UTC')
        charts = [fetch_chart(config['TWELVEDATA_API_KEY'], interval, minutes, now)
                  for interval, minutes in [('5min', 5), ('15min', 15), ('1h', 60)]]
        for interval, image, caption in charts:
            response = requests.post(
                f"https://api.telegram.org/bot{config['TELEGRAM_BOT_TOKEN']}/sendPhoto",
                data={'chat_id': config['TELEGRAM_CHAT_ID'], 'caption': caption},
                files={'photo': (f'xauusd_{interval}.png', image, 'image/png')},
                timeout=(10, 60),
            )
            if response.status_code != 200 or not response.json().get('ok'):
                raise RuntimeError(f'Telegram sendPhoto failed: HTTP {response.status_code}')
            image.close()
        print('三张测试图已发送；未调用 Gemini，未生成信号。')
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)
    except Exception as exc:
        print(f'测试停止：{type(exc).__name__}；为保护密钥不输出原始请求或响应。')
        sys.exit(1)


if __name__ == '__main__':
    main()
