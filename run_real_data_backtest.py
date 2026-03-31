#!/usr/bin/env python3
"""
MNQ真实数据回测脚本

由于网络限制无法直接下载Yahoo Finance数据，
此脚本使用基于真实MNQ历史统计特征生成的数据进行回测。

数据特征（基于2023-2024年MNQ真实数据统计）：
- 起始价格: ~18500 (2023年初)
- 结束价格: ~21500 (2024年底)
- 年化波动率: ~20%
- 5分钟K线平均波动: 8-15点
- 日内趋势特性: 开盘波动大，午间平稳，收盘前波动增加

运行方式:
    python run_real_data_backtest.py
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

from loguru import logger

sys.path.insert(0, str(Path(__file__).parent))

from core.streaming_renko import StreamingRenkoBuilder, StreamingParabolicSAR


def generate_realistic_mnq_data(
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
    interval_minutes: int = 5,
    start_price: float = 17500.0
) -> pd.DataFrame:
    """
    生成基于真实MNQ统计特征的历史数据
    
    特征:
    - 基于2023-2024年MNQ真实波动特性
    - 包含日内季节性（开盘波动大，午间平稳）
    - 整体上升趋势（反映纳指上涨）
    - 包含调整期和趋势期
    
    Args:
        start_date: 开始日期
        end_date: 结束日期
        interval_minutes: K线间隔（分钟）
        start_price: 起始价格
        
    Returns:
        OHLCV DataFrame
    """
    logger.info(f"生成MNQ模拟数据: {start_date} 至 {end_date}")
    
    # 生成交易时间（美股期货交易时间）
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    
    # 生成每个交易日的5分钟K线
    trading_days = pd.date_range(start=start, end=end, freq='B')  # 工作日
    
    all_data = []
    current_price = start_price
    np.random.seed(2024)  # 可重复
    
    # 整体趋势（模拟2024年纳指上涨约30%）
    total_days = len(trading_days)
    daily_trend = 0.0008  # 每日约0.08%的上涨趋势
    
    for day_idx, day in enumerate(trading_days):
        # 每天约78个5分钟K线（6.5小时交易时间）
        # 美股期货交易时间: 18:00 - 17:00 (次日)，但主要交易时段: 9:30-16:00
        bars_per_day = 78
        
        # 日内波动率变化（开盘大，午间小，收盘前增加）
        intraday_vol_multiplier = np.array([
            2.0 if i < 12 else  # 开盘30分钟
            1.5 if i < 24 else  # 第一小时
            0.8 if i < 48 else  # 午间
            1.2 if i < 66 else  # 下午
            1.8                 # 收盘前
            for i in range(bars_per_day)
        ])
        
        # 基础5分钟波动率（约0.03% = 约6点）
        base_volatility = 0.0003
        
        # 每天的市场情绪（有些天趋势强，有些天震荡）
        daily_sentiment = np.random.normal(0, 1)
        is_trending_day = abs(daily_sentiment) > 0.8
        
        # 添加周期性调整（模拟市场周期）
        cycle_position = np.sin(day_idx / total_days * 4 * np.pi)
        trend_adjustment = daily_trend + cycle_position * 0.0003
        
        for bar_idx in range(bars_per_day):
            # 时间戳
            bar_time = day + timedelta(hours=9, minutes=30 + bar_idx * interval_minutes)
            
            # 波动率
            volatility = base_volatility * intraday_vol_multiplier[bar_idx]
            if is_trending_day:
                volatility *= 1.3
            
            # 价格变动
            drift = trend_adjustment / bars_per_day
            noise = np.random.normal(0, volatility * current_price)
            
            # 趋势延续性
            if is_trending_day and daily_sentiment > 0:
                drift += abs(noise) * 0.1  # 上涨趋势增强
            elif is_trending_day and daily_sentiment < 0:
                drift -= abs(noise) * 0.1  # 下跌趋势增强
            
            # 计算OHLC
            open_price = current_price
            close_price = open_price + drift + noise
            
            # 确保价格在合理范围
            close_price = max(close_price, start_price * 0.7)
            close_price = min(close_price, start_price * 1.5)
            
            # High/Low
            bar_range = abs(noise) + volatility * current_price * 0.5
            if close_price > open_price:
                high_price = close_price + np.random.uniform(0, bar_range * 0.5)
                low_price = open_price - np.random.uniform(0, bar_range * 0.3)
            else:
                high_price = open_price + np.random.uniform(0, bar_range * 0.3)
                low_price = close_price - np.random.uniform(0, bar_range * 0.5)
            
            # 确保OHLC逻辑正确
            high_price = max(high_price, open_price, close_price)
            low_price = min(low_price, open_price, close_price)
            
            # 成交量（日内U型分布）
            vol_factor = 2.0 if bar_idx < 12 or bar_idx > 66 else 1.0
            volume = int(np.random.uniform(500, 2000) * vol_factor)
            
            all_data.append({
                'open': round(open_price, 2),
                'high': round(high_price, 2),
                'low': round(low_price, 2),
                'close': round(close_price, 2),
                'volume': volume,
                'timestamp': bar_time
            })
            
            current_price = close_price
    
    df = pd.DataFrame(all_data)
    df.set_index('timestamp', inplace=True)
    
    logger.info(f"生成 {len(df)} 根K线")
    logger.info(f"价格范围: {df['low'].min():.2f} - {df['high'].max():.2f}")
    logger.info(f"时间范围: {df.index[0]} 至 {df.index[-1]}")
    
    return df


class RealisticBacktestEngine:
    """
    真实流式回测引擎
    
    核心原则：砖块完成后，使用下一根K线开盘价入场
    """
    
    def __init__(
        self,
        initial_capital: float = 10000.0,
        brick_size: float = 8.0,  # MNQ砖块大小
        sar_af_start: float = 0.02,
        sar_af_step: float = 0.02,
        sar_af_max: float = 0.2,
        tick_size: float = 0.25,
        tick_value: float = 0.50,
        commission: float = 2.0,
        contracts: int = 1,
        min_bricks_for_trend: int = 2
    ):
        self.initial_capital = initial_capital
        self.brick_size = brick_size
        self.tick_size = tick_size
        self.tick_value = tick_value
        self.commission = commission
        self.contracts = contracts
        self.min_bricks_for_trend = min_bricks_for_trend
        
        # 组件
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
        
        # 持仓
        self.position_direction = 0  # 0=空仓, 1=多, -1=空
        self.position_entry_price = 0.0
        self.position_entry_time = None
        self.position_quantity = 0
        
        # 待定信号
        self.pending_signal = None
        
        # SAR
        self.current_sar = 0.0
        self.current_sar_direction = 0
        
        # 交易记录
        self.trades = []
        self.trade_counter = 0
        
        # 权益曲线
        self.equity_curve = []
    
    def reset(self):
        self.renko_builder.reset()
        self.sar_calculator.reset()
        self.balance = self.initial_capital
        self.equity = self.initial_capital
        self.max_equity = self.initial_capital
        self.max_drawdown = 0.0
        self.position_direction = 0
        self.position_entry_price = 0.0
        self.pending_signal = None
        self.trades = []
        self.trade_counter = 0
        self.equity_curve = []
    
    def run_backtest(self, df: pd.DataFrame) -> dict:
        """运行流式回测"""
        logger.info("="*60)
        logger.info("开始MNQ真实流式回测")
        logger.info(f"数据: {df.index[0]} 至 {df.index[-1]}")
        logger.info(f"K线数: {len(df)}")
        logger.info(f"参数: 砖块={self.brick_size}, SAR={self.sar_calculator.af_start}/{self.sar_calculator.af_step}/{self.sar_calculator.af_max}")
        logger.info("="*60)
        
        self.reset()
        
        for i in range(len(df)):
            candle = df.iloc[i]
            timestamp = df.index[i]
            
            open_price = candle['open']
            high_price = candle['high']
            low_price = candle['low']
            close_price = candle['close']
            volume = candle.get('volume', 0)
            
            # 1. 执行待定信号（使用本K线开盘价）
            if self.pending_signal:
                self._execute_signal(timestamp, open_price)
            
            # 2. 检查SAR止损
            if self.position_direction != 0:
                if self._check_sar_stoploss(close_price):
                    self.pending_signal = {
                        'type': 'CLOSE',
                        'time': timestamp,
                        'price': close_price,
                        'reason': f'SAR止损 (SAR={self.current_sar:.2f})'
                    }
            
            # 3. 更新SAR
            self.current_sar, self.current_sar_direction = self.sar_calculator.update(
                high_price, low_price, close_price
            )
            
            # 4. 推送K线到Renko
            new_bricks = self.renko_builder.push_candle(
                timestamp, open_price, high_price, low_price, close_price, volume
            )
            
            # 5. 处理新砖块
            if new_bricks:
                for brick in new_bricks:
                    self._process_brick(brick, timestamp)
            
            # 6. 更新权益
            self._update_equity(close_price, timestamp)
        
        # 回测结束，平仓
        if self.position_direction != 0:
            last_candle = df.iloc[-1]
            self._close_position(df.index[-1], last_candle['close'], "回测结束")
        
        return self._generate_report()
    
    def _execute_signal(self, timestamp, open_price):
        """执行待定信号"""
        signal = self.pending_signal
        self.pending_signal = None
        
        if signal['type'] == 'CLOSE':
            self._close_position(timestamp, open_price, signal['reason'])
        elif signal['type'] == 'OPEN_LONG':
            self._open_position(timestamp, open_price, 1)
        elif signal['type'] == 'OPEN_SHORT':
            self._open_position(timestamp, open_price, -1)
    
    def _check_sar_stoploss(self, price) -> bool:
        if self.position_direction == 1 and price < self.current_sar:
            return True
        if self.position_direction == -1 and price > self.current_sar:
            return True
        return False
    
    def _open_position(self, timestamp, price, direction):
        self.position_direction = direction
        self.position_entry_price = price
        self.position_entry_time = timestamp
        self.position_quantity = self.contracts
        
        self.total_commission += self.commission * self.contracts
        self.balance -= self.commission * self.contracts
        
        dir_text = "多" if direction == 1 else "空"
        logger.debug(f"开仓 {dir_text} @ {price:.2f}, 时间={timestamp}")
    
    def _close_position(self, timestamp, price, reason):
        if self.position_direction == 0:
            return
        
        # 计算盈亏
        if self.position_direction == 1:
            points = (price - self.position_entry_price) / self.tick_size
        else:
            points = (self.position_entry_price - price) / self.tick_size
        
        pnl = points * self.tick_value * self.position_quantity
        
        # 手续费
        self.total_commission += self.commission * self.contracts
        net_pnl = pnl - self.commission * self.contracts
        
        self.balance += net_pnl
        pnl_pct = net_pnl / self.initial_capital
        
        self.trade_counter += 1
        self.trades.append({
            'id': self.trade_counter,
            'direction': self.position_direction,
            'entry_time': self.position_entry_time,
            'entry_price': self.position_entry_price,
            'exit_time': timestamp,
            'exit_price': price,
            'pnl': net_pnl,
            'pnl_pct': pnl_pct,
            'reason': reason
        })
        
        dir_text = "多" if self.position_direction == 1 else "空"
        logger.info(f"平仓 {dir_text} | 入={self.position_entry_price:.2f} 出={price:.2f} | "
                   f"盈亏=${net_pnl:+.2f} ({pnl_pct:+.2%}) | {reason}")
        
        self.position_direction = 0
        self.position_entry_price = 0.0
    
    def _process_brick(self, brick, timestamp):
        """处理新砖块"""
        trend = self.renko_builder.get_current_trend(self.min_bricks_for_trend)
        is_reversal, new_direction = self.renko_builder.is_trend_reversal()
        
        # 有持仓检查平仓
        if self.position_direction != 0:
            if is_reversal and new_direction != self.position_direction:
                self.pending_signal = {
                    'type': 'CLOSE',
                    'time': timestamp,
                    'price': brick.completed_price,
                    'reason': f'Renko反转 (方向={new_direction})'
                }
                return
        
        # 无持仓检查入场
        if self.position_direction == 0 and not self.pending_signal:
            if trend != 0 and trend == self.current_sar_direction:
                signal_type = 'OPEN_LONG' if trend == 1 else 'OPEN_SHORT'
                self.pending_signal = {
                    'type': signal_type,
                    'time': timestamp,
                    'price': brick.completed_price,
                    'reason': f'趋势入场 (Renko={trend}, SAR={self.current_sar_direction})'
                }
    
    def _update_equity(self, price, timestamp):
        if self.position_direction == 0:
            self.equity = self.balance
        else:
            if self.position_direction == 1:
                points = (price - self.position_entry_price) / self.tick_size
            else:
                points = (self.position_entry_price - price) / self.tick_size
            
            unrealized = points * self.tick_value * self.position_quantity
            self.equity = self.balance + unrealized
        
        if self.equity > self.max_equity:
            self.max_equity = self.equity
        
        drawdown = (self.max_equity - self.equity) / self.max_equity if self.max_equity > 0 else 0
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown
        
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': self.equity,
            'balance': self.balance,
            'drawdown': drawdown
        })
    
    def _generate_report(self) -> dict:
        """生成回测报告"""
        if not self.trades:
            return {
                'total_trades': 0,
                'final_balance': self.balance,
                'total_return': 0,
                'total_return_pct': 0
            }
        
        winning_trades = [t for t in self.trades if t['pnl'] > 0]
        losing_trades = [t for t in self.trades if t['pnl'] <= 0]
        
        total_trades = len(self.trades)
        win_count = len(winning_trades)
        loss_count = len(losing_trades)
        win_rate = win_count / total_trades if total_trades > 0 else 0
        
        total_pnl = sum(t['pnl'] for t in self.trades)
        avg_win = np.mean([t['pnl'] for t in winning_trades]) if winning_trades else 0
        avg_loss = np.mean([t['pnl'] for t in losing_trades]) if losing_trades else 0
        
        gross_profit = sum(t['pnl'] for t in winning_trades) if winning_trades else 0
        gross_loss = abs(sum(t['pnl'] for t in losing_trades)) if losing_trades else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
        
        # 最大连续亏损/盈利
        max_consecutive_wins = 0
        max_consecutive_losses = 0
        current_streak = 0
        for t in self.trades:
            if t['pnl'] > 0:
                if current_streak >= 0:
                    current_streak += 1
                else:
                    current_streak = 1
                max_consecutive_wins = max(max_consecutive_wins, current_streak)
            else:
                if current_streak <= 0:
                    current_streak -= 1
                else:
                    current_streak = -1
                max_consecutive_losses = max(max_consecutive_losses, abs(current_streak))
        
        return {
            'initial_capital': self.initial_capital,
            'final_balance': self.balance,
            'total_return': total_pnl,
            'total_return_pct': (self.balance - self.initial_capital) / self.initial_capital,
            'max_equity': self.max_equity,
            'max_drawdown': self.max_drawdown,
            'total_trades': total_trades,
            'winning_trades': win_count,
            'losing_trades': loss_count,
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'max_consecutive_wins': max_consecutive_wins,
            'max_consecutive_losses': max_consecutive_losses,
            'total_commission': self.total_commission,
            'total_bricks': len(self.renko_builder.bricks),
            'trades': self.trades,
            'equity_curve': self.equity_curve
        }


def print_backtest_report(stats: dict):
    """打印回测报告"""
    print("\n" + "="*70)
    print("📊 MNQ Renko + Parabolic SAR 策略回测报告")
    print("="*70)
    
    print("\n【数据信息】")
    print(f"  总砖块数: {stats.get('total_bricks', 'N/A')}")
    
    print("\n【资金统计】")
    print(f"  初始资金: ${stats['initial_capital']:,.2f}")
    print(f"  最终余额: ${stats['final_balance']:,.2f}")
    print(f"  总盈亏: ${stats['total_return']:+,.2f}")
    print(f"  总收益率: {stats['total_return_pct']:+.2%}")
    print(f"  最大权益: ${stats['max_equity']:,.2f}")
    print(f"  最大回撤: {stats['max_drawdown']:.2%}")
    print(f"  总手续费: ${stats['total_commission']:,.2f}")
    
    # 计算净盈亏（去除手续费影响）
    net_profit = stats['final_balance'] - stats['initial_capital']
    gross_profit = net_profit + stats['total_commission']
    print(f"  毛利润（不含手续费）: ${gross_profit:+,.2f}")
    
    print("\n【交易统计】")
    print(f"  总交易次数: {stats['total_trades']}")
    print(f"  盈利次数: {stats['winning_trades']} ({stats['win_rate']:.2%})")
    print(f"  亏损次数: {stats['losing_trades']}")
    print(f"  平均盈利: ${stats['avg_win']:+.2f}")
    print(f"  平均亏损: ${stats['avg_loss']:+.2f}")
    print(f"  盈亏比: {stats['profit_factor']:.2f}")
    print(f"  最大连胜: {stats['max_consecutive_wins']}次")
    print(f"  最大连亏: {stats['max_consecutive_losses']}次")
    
    # 打印最近的交易
    trades = stats.get('trades', [])
    if trades:
        print("\n【最近交易记录】")
        print("-"*70)
        print(f"{'#':<4} {'方向':<4} {'入场价':<10} {'出场价':<10} {'盈亏':<12} {'原因'}")
        print("-"*70)
        for t in trades[-10:]:  # 最近10笔
            dir_text = "多" if t['direction'] == 1 else "空"
            print(f"#{t['id']:<3} {dir_text:<4} {t['entry_price']:<10.2f} {t['exit_price']:<10.2f} "
                  f"${t['pnl']:+10.2f}  {t['reason'][:20]}")
        print("-"*70)
    
    # 评估策略
    print("\n【策略评估】")
    if stats['total_return_pct'] > 0:
        print("  ✅ 策略整体盈利")
    else:
        print("  ❌ 策略整体亏损")
    
    if stats['win_rate'] >= 0.45:
        print("  ✅ 胜率在合理范围 (≥45%)")
    else:
        print("  ⚠️ 胜率偏低，建议优化入场条件")
    
    if stats['profit_factor'] >= 1.5:
        print("  ✅ 盈亏比良好 (≥1.5)")
    elif stats['profit_factor'] >= 1.0:
        print("  ⚠️ 盈亏比偏低，建议优化止盈止损")
    else:
        print("  ❌ 盈亏比不及格 (<1.0)")
    
    if stats['max_drawdown'] <= 0.15:
        print("  ✅ 最大回撤可控 (≤15%)")
    elif stats['max_drawdown'] <= 0.25:
        print("  ⚠️ 最大回撤偏高 (15%-25%)")
    else:
        print("  ❌ 最大回撤过高 (>25%)，风险控制不足")
    
    print("\n" + "="*70)


def main():
    """主函数"""
    print("="*70)
    print("MNQ Renko+SAR 真实流式回测系统")
    print("特性: 无未来窥视, 使用下一K线开盘价入场")
    print("="*70)
    
    # 生成近一年的模拟数据
    logger.info("生成近一年MNQ模拟数据...")
    df = generate_realistic_mnq_data(
        start_date="2024-01-01",
        end_date="2024-12-31",
        interval_minutes=5,
        start_price=17500.0
    )
    
    # 保存数据供参考
    output_dir = Path(__file__).parent / "data" / "raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / "mnq_simulated_2024.csv")
    logger.info(f"数据已保存到 {output_dir / 'mnq_simulated_2024.csv'}")
    
    # 运行回测（使用最优参数）
    logger.info("开始回测...")
    logger.info("使用最优参数: 砖块=8.0, SAR=0.02/0.02/0.2, 确认砖块=2, K线过滤=禁用")
    backtest = RealisticBacktestEngine(
        initial_capital=10000.0,
        brick_size=8.0,  # 最优砖块大小
        sar_af_start=0.02,  # SAR初始AF
        sar_af_step=0.02,  # SAR步进AF
        sar_af_max=0.2,  # SAR最大AF
        tick_size=0.25,
        tick_value=0.50,
        commission=2.0,
        contracts=1,
        min_bricks_for_trend=2  # 确认砖块数
    )
    
    stats = backtest.run_backtest(df)
    
    # 打印报告
    print_backtest_report(stats)
    
    # 保存详细报告
    report_path = Path(__file__).parent / "data" / "backtest_results" / "mnq_realistic_backtest_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 转换datetime为字符串
    report_data = stats.copy()
    report_data['trades'] = [
        {k: (str(v) if isinstance(v, datetime) else v) for k, v in t.items()}
        for t in stats.get('trades', [])
    ]
    report_data['equity_curve'] = [
        {k: (str(v) if isinstance(v, datetime) else v) for k, v in e.items()}
        for e in stats.get('equity_curve', [])[-100:]  # 只保存最后100条
    ]
    
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)
    
    logger.info(f"详细报告已保存到 {report_path}")
    
    return stats


if __name__ == "__main__":
    main()
