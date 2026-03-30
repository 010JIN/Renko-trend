"""
期货实时警报系统 (Futures Live Alert System)

专为 Popfirm 平台的 MNQ 和 MGC 短期交易设计
支持 5分钟/15分钟 级别的实时警报

功能:
1. 实时获取K线数据
2. 多时间框架分析
3. 实时警报生成
4. 声音和桌面通知
5. 交易日志记录
"""

import time
import pandas as pd
import yaml
import requests
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List
from loguru import logger

from strategies.short_term_alert_strategy import (
    ShortTermAlertStrategy, 
    TradingAlert, 
    SignalType
)


class FuturesLiveAlertSystem:
    """
    期货实时警报系统
    
    支持:
    - MNQ (Micro E-mini Nasdaq-100)
    - MGC (Micro Gold Futures)
    - 多时间框架分析
    - 实时通知
    """
    
    # 使用加密货币数据作为期货的替代
    # 在实际应用中，应使用真实的期货数据源
    SYMBOL_MAPPING = {
        "MNQ": "BTCUSDT",  # 使用BTC作为MNQ的替代数据源
        "MGC": "ETHUSDT",  # 使用ETH作为MGC的替代数据源
    }
    
    BINANCE_URL = "https://api.binance.com/api/v3/klines"
    
    def __init__(
        self,
        instrument: str = "MNQ",
        primary_timeframe: str = "5m",
        secondary_timeframe: str = "15m",
        config_path: str = "config/futures_config.yaml"
    ):
        """
        初始化系统
        
        Args:
            instrument: 交易品种 (MNQ/MGC)
            primary_timeframe: 主交易周期
            secondary_timeframe: 确认周期
            config_path: 配置文件路径
        """
        self.instrument = instrument
        self.primary_timeframe = primary_timeframe
        self.secondary_timeframe = secondary_timeframe
        
        # 加载配置
        self.config = self._load_config(config_path)
        
        # 初始化策略
        alert_config = self.config.get("alerts", {})
        reversal_config = alert_config.get("reversal", {})
        
        self.primary_strategy = ShortTermAlertStrategy(
            instrument=instrument,
            timeframe=primary_timeframe,
            rsi_oversold=reversal_config.get("rsi_oversold", 30),
            rsi_overbought=reversal_config.get("rsi_overbought", 70),
            min_confidence=0.6,
            atr_sl_multiplier=self.config.get("risk_management", {}).get("stop_loss", {}).get("atr_multiplier", 2.0),
            risk_reward_ratio=self.config.get("risk_management", {}).get("take_profit", {}).get("risk_reward_ratio", 2.0)
        )
        
        self.secondary_strategy = ShortTermAlertStrategy(
            instrument=instrument,
            timeframe=secondary_timeframe,
            rsi_oversold=reversal_config.get("rsi_oversold", 30),
            rsi_overbought=reversal_config.get("rsi_overbought", 70),
            min_confidence=0.6
        )
        
        # 数据存储
        self.primary_data: Optional[pd.DataFrame] = None
        self.secondary_data: Optional[pd.DataFrame] = None
        
        # 警报历史
        self.alert_history: List[TradingAlert] = []
        
        # 状态
        self.is_running = False
        self.last_alert_time: Optional[datetime] = None
        self.alert_cooldown = 300  # 5分钟冷却时间
        
        logger.info(f"初始化期货实时警报系统: {instrument} | "
                   f"主周期: {primary_timeframe} | 确认周期: {secondary_timeframe}")
    
    def _load_config(self, config_path: str) -> Dict:
        """加载配置文件"""
        try:
            path = Path(config_path)
            if path.exists():
                with open(path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f)
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}，使用默认配置")
        
        return {}
    
    def _get_symbol(self) -> str:
        """获取数据源符号"""
        return self.SYMBOL_MAPPING.get(self.instrument, "BTCUSDT")
    
    def _fetch_klines(self, interval: str, limit: int = 500) -> Optional[pd.DataFrame]:
        """
        获取K线数据
        
        Args:
            interval: 时间间隔 (1m, 5m, 15m, 1h等)
            limit: 数据条数
            
        Returns:
            OHLCV DataFrame
        """
        symbol = self._get_symbol()
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': limit
        }
        
        try:
            resp = requests.get(self.BINANCE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, dict) and 'code' in data:
                logger.error(f"API错误: {data.get('msg', 'Unknown error')}")
                return None
            
            if not data or not isinstance(data, list):
                logger.error(f"API返回数据格式错误")
                return None
            
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
            
            df = pd.DataFrame(klines)
            df.set_index('timestamp', inplace=True)
            return df
            
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return None
    
    def _fetch_latest_kline(self, interval: str) -> Optional[Dict]:
        """获取最新K线"""
        symbol = self._get_symbol()
        params = {
            'symbol': symbol,
            'interval': interval,
            'limit': 1
        }
        
        try:
            resp = requests.get(self.BINANCE_URL, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            
            if isinstance(data, dict) and 'code' in data:
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
    
    def _send_notification(self, alert: TradingAlert):
        """发送通知"""
        notification_config = self.config.get("notifications", {})
        
        # 声音通知
        if notification_config.get("sound", {}).get("enabled", True):
            print('\a')  # 系统蜂鸣
        
        # 控制台输出
        print(alert)
        
        # TODO: 实现 Telegram/Discord 通知
    
    def _check_alert_cooldown(self) -> bool:
        """检查是否在冷却期内"""
        if self.last_alert_time is None:
            return False
        
        elapsed = (datetime.now() - self.last_alert_time).total_seconds()
        return elapsed < self.alert_cooldown
    
    def _validate_alert_with_secondary(self, primary_alert: TradingAlert) -> bool:
        """
        使用次级时间框架验证警报
        
        Returns:
            True 如果验证通过
        """
        if self.secondary_data is None or len(self.secondary_data) < 20:
            return True  # 数据不足时默认通过
        
        secondary_alert = self.secondary_strategy.generate_alert(self.secondary_data)
        
        # 如果次级周期也有同向信号，验证通过
        if secondary_alert:
            if primary_alert.direction == secondary_alert.direction:
                logger.info(f"次级周期 ({self.secondary_timeframe}) 确认信号方向一致")
                return True
            else:
                logger.warning(f"次级周期 ({self.secondary_timeframe}) 信号方向不一致，降低置信度")
                return False
        
        # 没有次级信号时，检查趋势
        return True
    
    def analyze(self) -> Optional[TradingAlert]:
        """
        执行分析并生成警报
        
        Returns:
            TradingAlert 或 None
        """
        # 获取数据
        self.primary_data = self._fetch_klines(self.primary_timeframe)
        self.secondary_data = self._fetch_klines(self.secondary_timeframe)
        
        if self.primary_data is None or len(self.primary_data) < 20:
            logger.warning("主周期数据不足")
            return None
        
        # 检查冷却期
        if self._check_alert_cooldown():
            logger.debug("警报冷却期内，跳过")
            return None
        
        # 生成主周期警报
        alert = self.primary_strategy.generate_alert(self.primary_data)
        
        if alert:
            # 次级周期验证
            if self._validate_alert_with_secondary(alert):
                self.alert_history.append(alert)
                self.last_alert_time = datetime.now()
                self._send_notification(alert)
                return alert
            else:
                # 降低置信度
                alert.confidence *= 0.7
                if alert.confidence >= 0.5:
                    alert.reasons.append("注意：次级周期未确认")
                    self.alert_history.append(alert)
                    self.last_alert_time = datetime.now()
                    self._send_notification(alert)
                    return alert
        
        return None
    
    def run_once(self) -> Optional[TradingAlert]:
        """执行一次分析"""
        return self.analyze()
    
    def run_live(self, update_interval: int = 60):
        """
        运行实时监控
        
        Args:
            update_interval: 更新间隔（秒）
        """
        logger.info("="*60)
        logger.info(f"🚀 启动 {self.instrument} 实时警报系统")
        logger.info(f"   主周期: {self.primary_timeframe}")
        logger.info(f"   确认周期: {self.secondary_timeframe}")
        logger.info(f"   更新间隔: {update_interval}秒")
        logger.info("="*60)
        
        self.is_running = True
        
        try:
            while self.is_running:
                # 显示状态
                self._print_status()
                
                # 执行分析
                alert = self.analyze()
                
                if alert:
                    logger.info(f"⚠️  生成警报: {alert.signal_type.value}")
                
                # 等待下一次更新
                time.sleep(update_interval)
                
        except KeyboardInterrupt:
            logger.info("收到停止信号，正在关闭系统...")
            self.stop()
        
        except Exception as e:
            logger.error(f"系统运行出错: {e}")
            self.stop()
    
    def stop(self):
        """停止系统"""
        self.is_running = False
        
        # 保存警报历史
        self._save_alert_history()
        
        logger.info("系统已停止")
    
    def _print_status(self):
        """打印当前状态"""
        if self.primary_data is None:
            return
        
        current_price = self.primary_data['close'].iloc[-1]
        
        print("\n" + "-"*60)
        print(f"📊 {self.instrument} | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   价格: {current_price:.2f}")
        print(f"   警报数: {len(self.alert_history)}")
        
        if self.alert_history:
            last_alert = self.alert_history[-1]
            print(f"   最近警报: {last_alert.signal_type.value} @ {last_alert.timestamp}")
        
        print("-"*60)
    
    def _save_alert_history(self):
        """保存警报历史"""
        if not self.alert_history:
            return
        
        save_dir = Path("data/processed")
        save_dir.mkdir(parents=True, exist_ok=True)
        
        alerts_data = []
        for alert in self.alert_history:
            alerts_data.append({
                'timestamp': alert.timestamp,
                'instrument': alert.instrument,
                'signal_type': alert.signal_type.value,
                'direction': 'LONG' if alert.direction == 1 else 'SHORT',
                'price': alert.price,
                'entry_price': alert.entry_price,
                'stop_loss': alert.stop_loss,
                'take_profit': alert.take_profit,
                'confidence': alert.confidence,
                'timeframe': alert.timeframe,
                'patterns': '; '.join(alert.patterns),
                'reasons': '; '.join(alert.reasons),
                'risk_reward_ratio': alert.risk_reward_ratio
            })
        
        df = pd.DataFrame(alerts_data)
        filename = save_dir / f"alerts_{self.instrument}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename, index=False)
        logger.info(f"警报历史已保存到: {filename}")
    
    def get_summary(self) -> Dict:
        """获取系统摘要"""
        return {
            "instrument": self.instrument,
            "primary_timeframe": self.primary_timeframe,
            "secondary_timeframe": self.secondary_timeframe,
            "total_alerts": len(self.alert_history),
            "last_alert": self.alert_history[-1] if self.alert_history else None,
            "is_running": self.is_running
        }


def print_banner():
    """打印启动横幅"""
    banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║     🎯 期货短期交易警报系统 (Futures Short-term Alert)       ║
║                                                               ║
║     支持品种: MNQ (Micro E-mini Nasdaq) / MGC (Micro Gold)   ║
║     时间框架: 5分钟 / 15分钟                                  ║
║                                                               ║
║     信号类型:                                                 ║
║       • 反转信号 (Reversal)                                   ║
║       • 突破信号 (Breakout)                                   ║
║       • 顺势信号 (Trend Following)                            ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
"""
    print(banner)


# ==========================================
# 主程序入口
# ==========================================

if __name__ == "__main__":
    import argparse
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="期货实时警报系统")
    parser.add_argument("--instrument", "-i", type=str, default="MNQ",
                       choices=["MNQ", "MGC"],
                       help="交易品种 (MNQ/MGC)")
    parser.add_argument("--primary-tf", "-p", type=str, default="5m",
                       help="主交易周期 (1m/5m/15m)")
    parser.add_argument("--secondary-tf", "-s", type=str, default="15m",
                       help="确认周期 (5m/15m/1h)")
    parser.add_argument("--interval", "-n", type=int, default=60,
                       help="更新间隔（秒）")
    parser.add_argument("--once", action="store_true",
                       help="只运行一次分析")
    
    args = parser.parse_args()
    
    # 打印横幅
    print_banner()
    
    # 初始化系统
    system = FuturesLiveAlertSystem(
        instrument=args.instrument,
        primary_timeframe=args.primary_tf,
        secondary_timeframe=args.secondary_tf
    )
    
    if args.once:
        # 单次分析模式
        logger.info("执行单次分析...")
        alert = system.run_once()
        
        if alert:
            print("\n✅ 生成了交易警报!")
        else:
            print("\n❌ 当前没有符合条件的交易信号")
        
        # 显示摘要
        summary = system.get_summary()
        print(f"\n系统摘要: {summary}")
    else:
        # 实时监控模式
        system.run_live(update_interval=args.interval)
