"""
MNQ 真实流式回测系统 (Realistic Streaming Backtest)

关键特性：
1. 使用真实历史数据（NQ期货/QQQ ETF近1年）
2. 逐根K线推送，动态构建砖块
3. 砖块完成后使用下一根K线开盘价入场
4. 无未来窥视（Look-Ahead Bias）

入场逻辑：
- 当砖块完成时，等待下一根K线
- 使用下一根K线的开盘价作为实际入场价格
- 这模拟了真实交易中"看到信号后下单"的过程
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
import json
import warnings
warnings.filterwarnings('ignore')

from loguru import logger
import sys

sys.path.insert(0, str(Path(__file__).parent))

from core.streaming_renko import StreamingRenkoBuilder, StreamingParabolicSAR, RenkoBrick


@dataclass
class TradeRecord:
    """交易记录"""
    trade_id: int
    direction: int  # 1=多, -1=空
    entry_time: datetime
    entry_price: float  # 实际入场价（下一根K线开盘价）
    signal_price: float  # 信号产生时价格（砖块完成价格）
    exit_time: datetime = None
    exit_price: float = 0.0
    quantity: int = 1
    pnl: float = 0.0
    pnl_pct: float = 0.0
    exit_reason: str = ""
    brick_num_entry: int = 0
    brick_num_exit: int = 0


@dataclass
class PendingSignal:
    """待执行的信号（等待下一根K线入场）"""
    signal_type: str  # 'OPEN_LONG', 'OPEN_SHORT', 'CLOSE'
    signal_time: datetime
    signal_price: float
    brick_num: int
    direction: int = 0  # 入场方向
    reason: str = ""


class RealisticStreamingBacktest:
    """
    真实流式回测系统
    
    核心原则：
    1. 砖块完成 → 产生信号 → 等待下一根K线 → 使用开盘价入场
    2. 止损止盈也在新K线开盘时执行
    3. 完全消除未来窥视偏差
    """
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        brick_size: float = 10.0,  # MNQ砖块大小（点）
        sar_af_start: float = 0.02,
        sar_af_step: float = 0.02,
        sar_af_max: float = 0.2,
        tick_size: float = 0.25,  # MNQ最小变动
        tick_value: float = 0.50,  # MNQ每跳价值
        commission: float = 2.0,  # 每合约手续费
        contracts: int = 1,  # 每笔合约数
        min_bricks_for_trend: int = 2,  # 趋势确认砖块数
        use_sar_stoploss: bool = True
    ):
        self.initial_capital = initial_capital
        self.brick_size = brick_size
        self.tick_size = tick_size
        self.tick_value = tick_value
        self.commission = commission
        self.contracts = contracts
        self.min_bricks_for_trend = min_bricks_for_trend
        self.use_sar_stoploss = use_sar_stoploss
        
        # 核心组件
        self.renko_builder = StreamingRenkoBuilder(brick_size=brick_size)
        self.sar_calculator = StreamingParabolicSAR(
            af_start=sar_af_start,
            af_step=sar_af_step,
            af_max=sar_af_max
        )
        
        # 账户状态
        self.balance = initial_capital
        self.equity = initial_capital
        self.max_equity = initial_capital
        self.max_drawdown = 0.0
        self.total_commission = 0.0
        
        # 持仓状态
        self.position_direction = 0  # 0=空仓, 1=多, -1=空
        self.position_entry_price = 0.0
        self.position_entry_time = None
        self.position_quantity = 0
        self.position_brick_num = 0
        
        # 当前SAR
        self.current_sar = 0.0
        self.current_sar_direction = 0
        
        # 待执行信号（砖块完成后等待下一K线入场）
        self.pending_signal: Optional[PendingSignal] = None
        
        # 交易记录
        self.trades: List[TradeRecord] = []
        self.trade_counter = 0
        
        # 权益曲线
        self.equity_curve: List[Dict] = []
        
        logger.info(f"初始化真实流式回测: 本金=${initial_capital}, 砖块={brick_size}点")
    
    def reset(self):
        """重置回测状态"""
        self.renko_builder.reset()
        self.sar_calculator.reset()
        
        self.balance = self.initial_capital
        self.equity = self.initial_capital
        self.max_equity = self.initial_capital
        self.max_drawdown = 0.0
        self.total_commission = 0.0
        
        self.position_direction = 0
        self.position_entry_price = 0.0
        self.position_entry_time = None
        self.position_quantity = 0
        self.position_brick_num = 0
        
        self.current_sar = 0.0
        self.current_sar_direction = 0
        
        self.pending_signal = None
        self.trades = []
        self.trade_counter = 0
        self.equity_curve = []
    
    def _check_sar_stoploss(self, current_price: float) -> bool:
        """检查SAR止损"""
        if not self.use_sar_stoploss or self.position_direction == 0:
            return False
        
        if self.position_direction == 1:  # 多头
            if current_price < self.current_sar:
                return True
        else:  # 空头
            if current_price > self.current_sar:
                return True
        
        return False
    
    def _execute_pending_signal(
        self,
        timestamp: datetime,
        open_price: float
    ) -> Optional[TradeRecord]:
        """
        执行待定信号
        
        关键：使用新K线的开盘价作为实际入场价
        """
        if self.pending_signal is None:
            return None
        
        signal = self.pending_signal
        self.pending_signal = None
        
        if signal.signal_type == 'CLOSE':
            # 平仓
            return self._close_position(timestamp, open_price, signal.reason, signal.brick_num)
        
        elif signal.signal_type in ['OPEN_LONG', 'OPEN_SHORT']:
            # 开仓
            direction = 1 if signal.signal_type == 'OPEN_LONG' else -1
            self._open_position(timestamp, open_price, direction, signal.brick_num, signal.signal_price)
        
        return None
    
    def _open_position(
        self,
        timestamp: datetime,
        entry_price: float,
        direction: int,
        brick_num: int,
        signal_price: float
    ):
        """开仓"""
        self.position_direction = direction
        self.position_entry_price = entry_price
        self.position_entry_time = timestamp
        self.position_quantity = self.contracts
        self.position_brick_num = brick_num
        
        # 手续费
        self.total_commission += self.commission * self.contracts
        self.balance -= self.commission * self.contracts
        
        direction_text = "做多 🟢" if direction == 1 else "做空 🔴"
        logger.debug(f"开仓 | {direction_text} | "
                    f"信号价={signal_price:.2f} → 实际入场={entry_price:.2f} | "
                    f"砖块#{brick_num} | 时间={timestamp}")
    
    def _close_position(
        self,
        timestamp: datetime,
        exit_price: float,
        reason: str,
        brick_num: int
    ) -> TradeRecord:
        """平仓"""
        if self.position_direction == 0:
            return None
        
        # 计算盈亏
        if self.position_direction == 1:
            points_pnl = (exit_price - self.position_entry_price) / self.tick_size
        else:
            points_pnl = (self.position_entry_price - exit_price) / self.tick_size
        
        dollar_pnl = points_pnl * self.tick_value * self.position_quantity
        
        # 扣除手续费
        self.total_commission += self.commission * self.contracts
        net_pnl = dollar_pnl - self.commission * self.contracts
        
        # 更新余额
        self.balance += net_pnl
        pnl_pct = net_pnl / self.initial_capital
        
        # 创建交易记录
        self.trade_counter += 1
        trade = TradeRecord(
            trade_id=self.trade_counter,
            direction=self.position_direction,
            entry_time=self.position_entry_time,
            entry_price=self.position_entry_price,
            signal_price=self.position_entry_price,  # 简化处理
            exit_time=timestamp,
            exit_price=exit_price,
            quantity=self.position_quantity,
            pnl=net_pnl,
            pnl_pct=pnl_pct,
            exit_reason=reason,
            brick_num_entry=self.position_brick_num,
            brick_num_exit=brick_num
        )
        self.trades.append(trade)
        
        direction_text = "做多 🟢" if self.position_direction == 1 else "做空 🔴"
        logger.info(f"平仓 | {direction_text} | "
                   f"进场={self.position_entry_price:.2f} → 出场={exit_price:.2f} | "
                   f"盈亏=${net_pnl:+.2f} ({pnl_pct:+.2%}) | "
                   f"原因: {reason}")
        
        # 清空持仓
        self.position_direction = 0
        self.position_entry_price = 0.0
        self.position_entry_time = None
        self.position_quantity = 0
        
        return trade
    
    def _update_equity(self, current_price: float, timestamp: datetime):
        """更新权益"""
        if self.position_direction == 0:
            self.equity = self.balance
        else:
            if self.position_direction == 1:
                points_pnl = (current_price - self.position_entry_price) / self.tick_size
            else:
                points_pnl = (self.position_entry_price - current_price) / self.tick_size
            
            unrealized_pnl = points_pnl * self.tick_value * self.position_quantity
            self.equity = self.balance + unrealized_pnl
        
        # 更新最大权益和回撤
        if self.equity > self.max_equity:
            self.max_equity = self.equity
        
        drawdown = (self.max_equity - self.equity) / self.max_equity if self.max_equity > 0 else 0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        # 记录权益曲线
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': self.equity,
            'balance': self.balance,
            'drawdown': drawdown
        })
    
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """
        运行真实流式回测
        
        核心流程（每根K线）：
        1. 先执行待定信号（使用本K线开盘价）
        2. 检查SAR止损
        3. 更新SAR
        4. 推送K线到Renko构建器
        5. 如果有新砖块，产生待定信号（下一K线执行）
        
        Args:
            df: OHLCV数据（必须包含 open, high, low, close, volume）
            
        Returns:
            回测统计结果
        """
        logger.info("="*60)
        logger.info("开始真实流式回测 (无未来窥视)")
        logger.info("="*60)
        logger.info(f"数据范围: {df.index[0]} 至 {df.index[-1]}")
        logger.info(f"K线数量: {len(df)}")
        
        self.reset()
        
        # 遍历每根K线
        for i in range(len(df)):
            candle = df.iloc[i]
            timestamp = df.index[i]
            
            open_price = candle['open']
            high_price = candle['high']
            low_price = candle['low']
            close_price = candle['close']
            volume = candle.get('volume', 0)
            
            # 步骤1: 执行待定信号（使用本K线开盘价）
            if self.pending_signal is not None:
                self._execute_pending_signal(timestamp, open_price)
            
            # 步骤2: 检查SAR止损（使用当前价格）
            if self._check_sar_stoploss(close_price):
                # 产生平仓信号，下一K线执行
                brick_num = self.renko_builder.brick_counter
                self.pending_signal = PendingSignal(
                    signal_type='CLOSE',
                    signal_time=timestamp,
                    signal_price=close_price,
                    brick_num=brick_num,
                    reason=f"SAR止损 (SAR={self.current_sar:.2f})"
                )
            
            # 步骤3: 更新SAR
            self.current_sar, self.current_sar_direction = self.sar_calculator.update(
                high_price, low_price, close_price
            )
            
            # 步骤4: 推送K线到Renko构建器
            new_bricks = self.renko_builder.push_candle(
                timestamp, open_price, high_price, low_price, close_price, volume
            )
            
            # 步骤5: 如果有新砖块，处理信号
            if new_bricks:
                for brick in new_bricks:
                    self._process_new_brick(brick, timestamp)
            
            # 步骤6: 更新权益
            self._update_equity(close_price, timestamp)
        
        # 回测结束，强制平仓
        if self.position_direction != 0:
            last_price = df.iloc[-1]['close']
            last_time = df.index[-1]
            self._close_position(
                last_time, last_price, "回测结束平仓",
                self.renko_builder.brick_counter
            )
        
        # 计算统计
        stats = self._calculate_statistics(df)
        
        logger.info("="*60)
        logger.info("回测完成")
        logger.info("="*60)
        
        return stats
    
    def _process_new_brick(self, brick: RenkoBrick, timestamp: datetime):
        """
        处理新形成的砖块
        
        产生待定信号，等待下一根K线入场
        """
        trend = self.renko_builder.get_current_trend(self.min_bricks_for_trend)
        is_reversal, new_direction = self.renko_builder.is_trend_reversal()
        
        # 有持仓时检查是否需要平仓/反手
        if self.position_direction != 0:
            # 趋势反转 → 平仓
            if is_reversal and new_direction != self.position_direction:
                self.pending_signal = PendingSignal(
                    signal_type='CLOSE',
                    signal_time=timestamp,
                    signal_price=brick.completed_price,
                    brick_num=brick.brick_num,
                    reason=f"Renko反转 (方向={new_direction})"
                )
                return
        
        # 无持仓时检查是否入场
        if self.position_direction == 0 and self.pending_signal is None:
            # 趋势确认 + SAR同向 → 入场
            if trend != 0 and trend == self.current_sar_direction:
                signal_type = 'OPEN_LONG' if trend == 1 else 'OPEN_SHORT'
                self.pending_signal = PendingSignal(
                    signal_type=signal_type,
                    signal_time=timestamp,
                    signal_price=brick.completed_price,
                    brick_num=brick.brick_num,
                    direction=trend,
                    reason=f"趋势入场 (Renko={trend}, SAR={self.current_sar_direction})"
                )
    
    def _calculate_statistics(self, df: pd.DataFrame) -> Dict:
        """计算回测统计"""
        if not self.trades:
            return {
                'total_trades': 0,
                'final_balance': self.balance,
                'total_return': 0,
                'total_return_pct': 0,
                'win_rate': 0,
                'max_drawdown': self.max_drawdown,
                'total_bricks': len(self.renko_builder.bricks)
            }
        
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl <= 0]
        
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0
        
        total_pnl = sum(t.pnl for t in self.trades)
        total_return_pct = (self.balance - self.initial_capital) / self.initial_capital
        
        avg_win = np.mean([t.pnl for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t.pnl for t in losing_trades]) if losing_trades else 0
        
        profit_factor = (
            abs(sum(t.pnl for t in winning_trades) / sum(t.pnl for t in losing_trades))
            if losing_trades and sum(t.pnl for t in losing_trades) != 0
            else float('inf') if winning_trades else 0
        )
        
        stats = {
            'initial_capital': self.initial_capital,
            'final_balance': self.balance,
            'total_return': total_pnl,
            'total_return_pct': total_return_pct,
            'max_equity': self.max_equity,
            'max_drawdown': self.max_drawdown,
            'total_trades': total_trades,
            'winning_trades': win_count,
            'losing_trades': loss_count,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_commission': self.total_commission,
            'total_bricks': len(self.renko_builder.bricks),
            'data_start': df.index[0],
            'data_end': df.index[-1],
            'data_bars': len(df),
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }
        
        return stats
    
    def print_statistics(self, stats: Dict):
        """打印统计结果"""
        print("\n" + "="*60)
        print("📊 真实流式回测统计 (无未来窥视)")
        print("="*60)
        
        print(f"\n📅 数据范围:")
        print(f"  开始: {stats['data_start']}")
        print(f"  结束: {stats['data_end']}")
        print(f"  K线数: {stats['data_bars']:,}")
        print(f"  砖块数: {stats['total_bricks']}")
        
        print(f"\n💰 资金情况:")
        print(f"  初始资金: ${stats['initial_capital']:,.2f}")
        print(f"  最终余额: ${stats['final_balance']:,.2f}")
        print(f"  总盈亏: ${stats['total_return']:+,.2f}")
        print(f"  总收益率: {stats['total_return_pct']:+.2%}")
        print(f"  最大权益: ${stats['max_equity']:,.2f}")
        print(f"  最大回撤: {stats['max_drawdown']:.2%}")
        print(f"  总手续费: ${stats['total_commission']:,.2f}")
        
        print(f"\n📈 交易统计:")
        print(f"  总交易次数: {stats['total_trades']}")
        print(f"  盈利次数: {stats['winning_trades']} ({stats['win_rate']:.2%})")
        print(f"  亏损次数: {stats['losing_trades']}")
        print(f"  平均盈利: ${stats['avg_win']:+.2f}")
        print(f"  平均亏损: ${stats['avg_loss']:+.2f}")
        print(f"  盈亏比: {stats['profit_factor']:.2f}")
        
        print("="*60)
    
    def print_trades(self, max_trades: int = 20):
        """打印交易记录"""
        if not self.trades:
            print("无交易记录")
            return
        
        print("\n" + "="*60)
        print("📝 交易记录 (使用下一K线开盘价入场)")
        print("="*60)
        
        trades_to_show = self.trades[:max_trades]
        for trade in trades_to_show:
            direction = "🟢多" if trade.direction == 1 else "🔴空"
            print(f"#{trade.trade_id} | {direction} | "
                  f"入场={trade.entry_price:.2f} → 出场={trade.exit_price:.2f} | "
                  f"盈亏=${trade.pnl:+.2f} | {trade.exit_reason}")
        
        if len(self.trades) > max_trades:
            print(f"... 还有 {len(self.trades) - max_trades} 笔交易")
        
        print("="*60)


def download_real_data(
    symbol: str = "NQ=F",
    period: str = "1y",
    interval: str = "5m"
) -> pd.DataFrame:
    """
    下载真实的NQ期货数据
    
    Args:
        symbol: 股票/期货代码
        period: 数据周期
        interval: K线间隔
    
    Returns:
        OHLCV DataFrame
    """
    try:
        import yfinance as yf
        
        logger.info(f"下载真实数据: {symbol}, 周期={period}, 间隔={interval}")
        
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        
        if df.empty:
            logger.warning(f"{symbol} 数据为空，尝试QQQ")
            ticker = yf.Ticker("QQQ")
            df = ticker.history(period=period, interval=interval)
            
            if not df.empty:
                # QQQ转换为MNQ近似价格
                df = df.copy()
                multiplier = 45  # 近似乘数
                df['Open'] *= multiplier
                df['High'] *= multiplier
                df['Low'] *= multiplier
                df['Close'] *= multiplier
                logger.info(f"使用QQQ × {multiplier}作为MNQ代理")
        
        if df.empty:
            raise ValueError("无法获取数据")
        
        # 标准化列名
        df.columns = [c.lower() for c in df.columns]
        
        # 删除可能的NaN
        df = df.dropna()
        
        logger.info(f"成功获取 {len(df)} 条K线数据")
        logger.info(f"时间范围: {df.index[0]} 至 {df.index[-1]}")
        logger.info(f"价格范围: {df['low'].min():.2f} - {df['high'].max():.2f}")
        
        return df
        
    except Exception as e:
        logger.error(f"下载数据失败: {e}")
        raise


def run_realistic_backtest(
    df: pd.DataFrame = None,
    brick_size: float = 10.0,
    sar_af_start: float = 0.02,
    sar_af_step: float = 0.02,
    sar_af_max: float = 0.2,
    min_bricks: int = 2
) -> Dict:
    """
    运行真实流式回测
    
    Args:
        df: OHLCV数据（如果为None则下载）
        brick_size: 砖块大小
        sar_*: SAR参数
        min_bricks: 趋势确认砖块数
        
    Returns:
        回测统计结果
    """
    # 获取数据
    if df is None:
        try:
            df = download_real_data(symbol="NQ=F", period="1y", interval="5m")
        except Exception as e:
            logger.warning(f"无法下载真实数据: {e}")
            logger.info("使用内置模拟数据生成器")
            # 使用内置的模拟数据生成器
            df = _generate_synthetic_data(n_bars=50000)
    
    # 创建回测系统
    backtest = RealisticStreamingBacktest(
        initial_capital=10000.0,
        brick_size=brick_size,
        sar_af_start=sar_af_start,
        sar_af_step=sar_af_step,
        sar_af_max=sar_af_max,
        min_bricks_for_trend=min_bricks
    )
    
    # 运行回测
    stats = backtest.run_backtest(df)
    
    # 打印结果
    backtest.print_statistics(stats)
    backtest.print_trades(20)
    
    return stats


def _generate_synthetic_data(n_bars: int = 50000) -> pd.DataFrame:
    """
    生成模拟的MNQ数据
    
    注意：这是临时后备方案，真实回测应使用真实数据
    使用更真实的MNQ价格波动模拟
    """
    logger.warning("⚠️ 使用模拟数据 - 真实回测需要真实历史数据")
    
    np.random.seed(42)
    start_price = 19800.0  # MNQ typical price (as of 2024)
    
    # Volatility estimate: MNQ 5-minute bars typically move ~10-20 points
    # With price ~19800, this is about 0.05-0.1%, using 0.02% as base volatility
    volatility = 0.0002
    
    # Generate realistic price series (random walk + mean reversion)
    prices = [start_price]
    for i in range(1, n_bars):
        drift = np.random.normal(0, volatility * prices[-1])
        mean_reversion = (start_price - prices[-1]) * 0.0001  # Slight mean reversion
        new_price = prices[-1] + drift + mean_reversion
        prices.append(max(new_price, start_price * 0.8))  # Floor at 80%
    
    prices = np.array(prices)
    timestamps = pd.date_range(start='2023-01-01', periods=n_bars, freq='5min')
    
    data = []
    for i, (ts, close) in enumerate(zip(timestamps, prices)):
        # Realistic 5-minute intra-bar range (~10 points)
        bar_range = prices[i] * 0.0005
        high = close + np.random.uniform(0, bar_range)
        low = close - np.random.uniform(0, bar_range)
        open_price = prices[i-1] if i > 0 else start_price
        
        high = max(high, open_price, close)
        low = min(low, open_price, close)
        
        data.append({
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': np.random.randint(1000, 10000)
        })
    
    df = pd.DataFrame(data, index=timestamps)
    logger.info(f"生成模拟数据: {len(df)}条K线, 价格范围 {df['low'].min():.2f} - {df['high'].max():.2f}")
    return df


if __name__ == "__main__":
    print("="*60)
    print("MNQ 真实流式回测系统")
    print("特性: 无未来窥视, 使用下一K线开盘价入场")
    print("="*60)
    
    # 运行回测
    stats = run_realistic_backtest(
        brick_size=10.0,
        sar_af_start=0.02,
        sar_af_step=0.02,
        sar_af_max=0.2,
        min_bricks=2
    )
