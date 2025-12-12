"""
实时交易系统：连接币安API实时采集K线数据，动态生成砖块并执行模拟交易
"""

import time
import pandas as pd
import sys
from pathlib import Path
from loguru import logger
import yaml
from datetime import datetime
import requests

sys.path.append(str(Path(__file__).parent))
from core.renko_builder import RenkoBuilder
from strategies.renko_reversal_strategy import RenkoReversalStrategy


class LiveTradingSystem:
    """实时交易系统"""
    
    def __init__(self, symbol=None, interval=None, method=None, renko_params=None, config_path: str = 'config/config.yaml'):
        """
        初始化实时交易系统
        支持动态参数优先于配置文件
        
        Args:
            symbol: 交易对
            interval: K线周期
            method: Renko方法
            renko_params: Renko方法参数
            config_path: 配置文件路径
        """
        # 先加载配置文件
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        self.data_cfg = self.config.get('data', {})
        self.renko_cfg = self.config.get('renko', {})
        
        # 动态参数优先
        self.symbol = symbol or self.data_cfg.get('symbol', 'BTCUSDT')
        self.interval = interval or self.data_cfg.get('interval', '1m')
        self.binance_url = 'https://api.binance.com/api/v3/klines'
        
        # 动态组装renko参数
        renko_args = dict(
            method=method or self.renko_cfg.get('method', 'fixed'),
            brick_size=self.renko_cfg.get('brick_size', 200.0),
            atr_period=self.renko_cfg.get('atr_period', 14),
            atr_multiplier=self.renko_cfg.get('atr_multiplier', 2.0),
            percentage=self.renko_cfg.get('percentage', 0.0035),
            log_base=self.renko_cfg.get('log_base', 10.0),
            use_wicks=self.renko_cfg.get('use_wicks', False)
        )
        if renko_params:
            renko_args.update(renko_params)
        self.builder = RenkoBuilder(**renko_args)
        
        # 初始化策略
        self.strategy = RenkoReversalStrategy(
            initial_capital=10000.0,
            commission_rate=0.0004,
            slippage_rate=0.0001
        )
        
        # K线数据集和统计
        self.df = pd.DataFrame()
        self.last_timestamp = None
        self.last_brick_count = 0
        self.trade_log = []
        
        logger.info(f"初始化实时交易系统: {self.symbol} {self.interval}")
        logger.info(f"砖块方法: {renko_args['method']} 参数: {renko_params}")
    
    def fetch_historical_klines(self, limit=500):
        """获取历史K线数据"""
        params = {
            'symbol': self.symbol,
            'interval': self.interval,
            'limit': limit
        }
        try:
            resp = requests.get(self.binance_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, dict) and 'code' in data:
                logger.error(f"API错误: {data.get('msg', 'Unknown error')}")
                return pd.DataFrame()
            
            if not data or not isinstance(data, list):
                logger.error(f"API返回数据格式错误")
                return pd.DataFrame()
            
            klines = []
            for k in data:
                if not isinstance(k, list) or len(k) < 6:
                    continue
                klines.append({
                    'timestamp': pd.to_datetime(int(k[0]), unit='ms'),
                    'open': float(k[1]),
                    'high': float(k[2]),
                    'low': float(k[3]),
                    'close': float(k[4]),
                    'volume': float(k[5])
                })
            return pd.DataFrame(klines)
        except Exception as e:
            logger.error(f"获取历史K线失败: {e}")
            return pd.DataFrame()
    
    def fetch_latest_kline(self):
        """获取最新K线"""
        params = {
            'symbol': self.symbol,
            'interval': self.interval,
            'limit': 1
        }
        try:
            resp = requests.get(self.binance_url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, dict) and 'code' in data:
                logger.error(f"API错误: {data.get('msg', 'Unknown error')}")
                return None
            
            if not data or not isinstance(data, list) or len(data) == 0:
                return None
            
            k = data[0]
            if not isinstance(k, list) or len(k) < 6:
                return None
                
            return {
                'timestamp': pd.to_datetime(int(k[0]), unit='ms'),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5])
            }
        except Exception as e:
            logger.error(f"获取最新K线失败: {e}")
            return None
    
    
    def count_consecutive_bricks(self, renko_df):
        """统计当前方向连续砖块数"""
        if renko_df.empty:
            return 0
        last_dir = renko_df.iloc[-1]['direction']
        count = 0
        for i in range(len(renko_df)-1, -1, -1):
            if renko_df.iloc[i]['direction'] == last_dir:
                count += 1
            else:
                break
        return count
    
    def process_new_kline(self, new_kline):
        """处理新K线并生成砖块（累计buffer方式，解决极难生成砖块问题）"""
        if not hasattr(self, '_buffer'):
            self._buffer = []
            self._last_brick_close = None
        self._buffer.append(new_kline)

        # 初始化last_brick_close
        if self._last_brick_close is None:
            self._last_brick_close = new_kline['open']

        # 用buffer尝试生成砖块
        buffer_df = pd.DataFrame(self._buffer).copy().reset_index(drop=True)
        buffer_df.at[0, 'open'] = self._last_brick_close
        renko_df = self.builder.build(buffer_df)

        if not renko_df.empty:
            brick = renko_df.iloc[0]
            signal = self.strategy.on_brick(brick)
            direction_text = "🟢 上涨" if brick['direction'] == 1 else "🔴 下跌"
            signal_text = {
                'hold': '持有',
                'open': '✅ 开仓',
                'reverse': '🔄 反向'
            }.get(signal, signal)

            # 统计当前方向连续砖块数
            if not hasattr(self, '_all_renko_df'):
                self._all_renko_df = pd.DataFrame()
            self._all_renko_df = pd.concat([self._all_renko_df, pd.DataFrame([brick])], ignore_index=True)
            consecutive = self.count_consecutive_bricks(self._all_renko_df)

            # 计算当前持仓收益
            current_pnl = 0.0
            if not self.strategy.position.is_empty:
                direction = self.strategy.position.direction
                entry_price = self.strategy.position.entry_price
                qty = self.strategy.position.quantity
                # 最新价格用当前砖块close
                price = brick['brick_close']
                if direction == 1:
                    current_pnl = (price - entry_price) * qty
                else:
                    current_pnl = (entry_price - price) * qty

            print("\n" + "="*60)
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 实时监控")
            print(f"⏰ 时间: {new_kline['timestamp']}")
            print(f"📊 生成砖块: {direction_text} | 价格: {brick['brick_close']:.2f}")
            print(f"💡 信号: {signal_text}")
            print(f"📦 当前方向连续砖块数: {consecutive}")
            print(f"💰 余额: ${self.strategy.balance:,.2f}")
            print(f"📈 权益: ${self.strategy.equity:,.2f}")
            if not self.strategy.position.is_empty:
                position_text = '多头🟢' if self.strategy.position.direction == 1 else '空头🔴'
                print(f"📍 持仓: {position_text} | 价格={self.strategy.position.entry_price:.2f} | 数量={self.strategy.position.quantity:.6f}")
                print(f"💹 当前持仓收益: {current_pnl:+.2f}")
            else:
                print(f"📍 持仓: 空仓")
            print(f"="*60 + "\n")
            if len(self.strategy.trades) > len(self.trade_log):
                print('\a', end='')
            self._last_brick_close = brick['brick_close']
            self._buffer = []
            stats = self.strategy.calculate_statistics()
            self.trade_log.append({
                'timestamp': datetime.now(),
                'equity': stats['final_balance'],
                'total_trades': stats['total_trades']
            })
    
    def start(self):
        """启动实时交易系统"""
        logger.info("="*70)
        logger.info("🚀 启动实时交易系统（币安API实时采集）")
        logger.info("="*70)
        
        # 获取初始历史数据
        logger.info(f"正在获取初始K线数据（{self.interval}周期）...")
        self.df = self.fetch_historical_klines(limit=500)
        if self.df.empty:
            logger.error("无法获取初始K线数据，退出系统")
            sys.exit(1)
        logger.info(f"已获取 {len(self.df)} 条历史K线")
        
        # 采集后立即输出砖块统计信息
        renko_df = self.builder.build(self.df)
        brick_count = len(renko_df)
        if brick_count > 0:
            last_brick = renko_df.iloc[-1]
            direction = '上涨🟢' if last_brick['direction'] == 1 else '下跌🔴'
            logger.info(f"[初始化] 500根K线共生成 {brick_count} 个砖块，当前方向：{direction}，最新砖块价：{last_brick['brick_close']:.2f}")
        else:
            logger.info(f"[初始化] 500根K线未生成任何砖块，请检查参数设置！")
        
        # 计算睡眠时间
        if self.interval.endswith('m'):
            sleep_sec = int(self.interval[:-1]) * 60
        elif self.interval.endswith('h'):
            sleep_sec = int(self.interval[:-1]) * 3600
        elif self.interval.endswith('d'):
            sleep_sec = int(self.interval[:-1]) * 86400
        else:
            sleep_sec = 60
        
        logger.info(f"开始实时采集，周期：{self.interval}（每{sleep_sec}秒刷新）")
        logger.info("按 Ctrl+C 停止系统\n")
        
        try:
            while True:
                # 获取最新K线
                new_kline = self.fetch_latest_kline()
                
                if new_kline is None:
                    logger.warning("获取最新K线失败，等待重试...")
                    time.sleep(10)
                    continue
                
                # 检查是否是新K线
                if self.last_timestamp is not None and new_kline['timestamp'] <= self.last_timestamp:
                    logger.debug(f"K线未更新，等待下一周期... (当前: {new_kline['timestamp']})")
                    time.sleep(sleep_sec // 2)
                    continue
                
                # 处理新K线
                self.last_timestamp = new_kline['timestamp']
                self.process_new_kline(new_kline)
                
                # 等待下一个周期
                time.sleep(sleep_sec)
                
        except KeyboardInterrupt:
            logger.info("\n收到停止信号，正在保存数据...")
            self.save_results()
            logger.info("系统已停止")
    
    def save_results(self):
        """保存交易结果"""
        # 保存净值曲线
        if self.trade_log:
            pd.DataFrame(self.trade_log).to_csv('data/processed/live_trading_equity.csv', index=False)
            logger.info("净值曲线已保存到 data/processed/live_trading_equity.csv")
        
        # 保存交易明细
        if self.strategy.trades:
            trades_df = pd.DataFrame([
                {
                    'trade_id': t.trade_id,
                    'direction': 'LONG' if t.direction == 1 else 'SHORT',
                    'entry_time': t.entry_time,
                    'entry_price': t.entry_price,
                    'exit_time': t.exit_time,
                    'exit_price': t.exit_price,
                    'quantity': t.quantity,
                    'pnl': t.pnl,
                    'pnl_pct': t.pnl_pct,
                    'balance_before': t.balance_before,
                    'balance_after': t.balance_after
                } for t in self.strategy.trades
            ])
            trades_df.to_csv('data/processed/live_trading_trades.csv', index=False)
            logger.info("交易明细已保存到 data/processed/live_trading_trades.csv")
        
        # 打印最终统计
        stats = self.strategy.calculate_statistics()
        logger.info("\n" + "="*70)
        logger.info("📊 最终统计")
        logger.info("="*70)
        logger.info(f"初始资金: ${self.strategy.initial_capital:,.2f}")
        logger.info(f"最终余额: ${stats['final_balance']:,.2f}")
        logger.info(f"总收益率: {stats['total_return_pct']*100:.2f}%")
        logger.info(f"总交易次数: {stats['total_trades']}")
        logger.info(f"胜率: {stats.get('win_rate', 0)*100:.2f}%")
        logger.info(f"最大回撤: {stats.get('max_drawdown', 0)*100:.2f}%")
        logger.info(f"盈利因子: {stats.get('profit_factor', 0):.2f}")
        logger.info(f"总手续费: ${stats.get('total_commission', 0):,.2f}")
        logger.info("="*70)


def get_user_params():
    """交互式获取用户参数"""
    symbol = input("请输入交易对（如 BTCUSDT，默认BTCUSDT）：") or "BTCUSDT"
    interval = input("请输入K线周期（如 1m/5m，默认1m）：") or "1m"
    method = input("请输入Renko方法（fixed/atr/percentage/log_percentage，默认fixed）：") or "fixed"
    # 根据不同方法提示不同参数
    if method == "fixed":
        brick_size = float(input("请输入砖块大小 brick_size（如 200）：") or 200)
        params = {"brick_size": brick_size}
    elif method == "atr":
        atr_period = int(input("请输入ATR周期 atr_period（如 14）：") or 14)
        atr_multiplier = float(input("请输入ATR倍数 atr_multiplier（如 2.0）：") or 2.0)
        params = {"atr_period": atr_period, "atr_multiplier": atr_multiplier}
    elif method == "percentage":
        percentage = float(input("请输入百分比 percentage（如 0.0035）：") or 0.0035)
        params = {"percentage": percentage}
    elif method == "log_percentage":
        percentage = float(input("请输入对数百分比 percentage（如 0.0035）：") or 0.0035)
        log_base = float(input("请输入对数底数 log_base（如 10.0）：") or 10.0)
        params = {"percentage": percentage, "log_base": log_base}
    else:
        print("方法无效，使用默认 fixed")
        method = "fixed"
        brick_size = float(input("请输入砖块大小 brick_size（如 200）：") or 200)
        params = {"brick_size": brick_size}
    return symbol, interval, method, params


def main():
    try:
        # 交互式参数输入
        symbol, interval, method, renko_params = get_user_params()
        print(f"参数确认：symbol={symbol}, interval={interval}, method={method}, params={renko_params}")

        # 创建实时交易系统，传递参数
        system = LiveTradingSystem(
            symbol=symbol,
            interval=interval,
            method=method,
            renko_params=renko_params
        )
        # 启动系统（阻塞运行）
        system.start()
    except Exception as e:
        logger.error(f"❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

    main()
