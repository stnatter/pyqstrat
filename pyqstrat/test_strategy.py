# $$_ Lines starting with # $$_* autogenerated by jup_mini. Do not modify these
# $$_markdown
# # Unit Tests for the Strategy class
# 
# ## Data Used
# Description of any files used as inputs
# 
# ## Data Created
# Description of any output files created
# $$_end_markdown
# $$_code
# $$_ %%checkall
import numpy as np
import pandas as pd
import pyqstrat as pq
import math
import os
from types import SimpleNamespace
from typing import Sequence

_logger = pq.get_child_logger(__name__)


def test_strategy() -> None:
    try:
        # If we are running from unit tests
        aapl_file_path = os.path.dirname(os.path.realpath(__file__)) + '/notebooks/data/AAPL.csv.gz'
        ibm_file_path = os.path.dirname(os.path.realpath(__file__)) + '/notebooks/data/IBM.csv.gz'
    except NameError:
        aapl_file_path = 'notebooks/data/AAPL.csv.gz'
        ibm_file_path = 'notebooks/data/IBM.csv.gz'

    aapl_prices = pd.read_csv(aapl_file_path)
    ibm_prices = pd.read_csv(ibm_file_path)

    end_time = '2023-01-05 12:00'

    aapl_prices = aapl_prices.query(f'timestamp <= "{end_time}"').sort_values(by='timestamp')
    ibm_prices = ibm_prices.query(f'timestamp <= "{end_time}"').sort_values(by='timestamp')

    timestamps = aapl_prices.timestamp.values.astype('M8[m]')

    ratio = aapl_prices.c / ibm_prices.c

    def zscore_indicator(contract_group: pq.ContractGroup, 
                         timestamps: np.ndarray, 
                         indicators: SimpleNamespace,
                         strategy_context: pq.StrategyContextType) -> np.ndarray:  # simple moving average
        ratio = indicators.ratio
        r = pd.Series(ratio).rolling(window=130)
        mean = r.mean()
        std = r.std(ddof=0)
        zscore = (ratio - mean) / std
        zscore = np.nan_to_num(zscore)
        return zscore

    def pair_strategy_signal(contract_group: pq.ContractGroup,
                             timestamps: np.ndarray,
                             indicators: SimpleNamespace, 
                             parent_signals: SimpleNamespace,
                             strategy_context: pq.StrategyContextType) -> np.ndarray: 
        # We don't need any indicators since the zscore is already part of the market data
        zscore = indicators.zscore
        signal = np.where(zscore > 1, 2, 0)
        signal = np.where(zscore < -1, -2, signal)
        signal = np.where((zscore > 0.5) & (zscore < 1), 1, signal)
        signal = np.where((zscore < -0.5) & (zscore > -1), -1, signal)
        if contract_group.name == 'ibm': signal = -1. * signal
        return signal

    def pair_entry_rule(contract_group: pq.ContractGroup,
                        i: int,
                        timestamps: np.ndarray,
                        indicators: SimpleNamespace,
                        signal: np.ndarray,
                        account: pq.Account,
                        orders: Sequence[pq.Order],
                        strategy_context: pq.StrategyContextType) -> list[pq.Order]:
        timestamp = timestamps[i]
        pq.assert_(math.isclose(account.position(contract_group, timestamp), 0))
        signal_value = signal[i]
        risk_percent = 0.1

        _orders: list[pq.Order] = []

        symbol = contract_group.name
        contract = contract_group.get_contract(symbol)
        if contract is None: contract = pq.Contract.create(symbol, contract_group=contract_group)

        curr_equity = account.equity(timestamp)
        order_qty = np.round(curr_equity * risk_percent / indicators.c[i] * np.sign(signal_value))
        _logger.info(f'order_qty: {order_qty} curr_equity: {curr_equity} timestamp: {timestamp}'
                     f' risk_percent: {risk_percent} indicator: {indicators.c[i]} signal_value: {signal_value}')
        reason_code = 'ENTER_LONG' if order_qty > 0 else 'ENTER_SHORT'
        _orders.append(pq.MarketOrder(contract=contract, 
                                      timestamp=timestamp, 
                                      qty=order_qty, 
                                      reason_code=reason_code))
        return _orders

    def pair_exit_rule(contract_group: pq.ContractGroup,
                       i: int,
                       timestamps: np.ndarray,
                       indicators: SimpleNamespace,
                       signal: np.ndarray,
                       account: pq.Account,
                       orders: Sequence[pq.Order],
                       strategy_context: pq.StrategyContextType) -> list[pq.Order]:
        timestamp = timestamps[i]
        curr_pos = account.position(contract_group, timestamp)
        pq.assert_(not math.isclose(curr_pos, 0))
        signal_value = signal[i]
        _orders: list[pq.Order] = []
        symbol = contract_group.name
        contract = contract_group.get_contract(symbol)
        if contract is None: contract = pq.Contract.create(symbol, contract_group=contract_group)
        if (curr_pos > 0 and signal_value == -1) or (curr_pos < 0 and signal_value == 1):
            order_qty = -curr_pos
            reason_code = 'EXIT_LONG' if order_qty < 0 else 'EXIT_SHORT'
            _orders.append(pq.MarketOrder(
                contract=contract, 
                timestamp=timestamp, 
                qty=order_qty, 
                reason_code=reason_code))
        return _orders

    def market_simulator(orders: Sequence[pq.Order],
                         i: int,
                         timestamps: np.ndarray,
                         indicators: dict[str, SimpleNamespace],
                         signals: dict[str, SimpleNamespace],
                         strategy_context: pq.StrategyContextType) -> list[pq.Trade]:
        trades = []

        timestamp = timestamps[i]

        for order in orders:
            trade_price = np.nan

            assert order.contract is not None
            cgroup = order.contract.contract_group
            ind = indicators[cgroup.name]
            o, h, l = ind.o[i], ind.h[i], ind.l[i]  # noqa

            # o, h, l = ind[f'{cgroup.name}_o'][i], ind[f'{cgroup.name}_h'][i], ind[f'{cgroup.name}_l'][i]  # noqa: E741  # l is ambiguous

            pq.assert_(isinstance(order, pq.MarketOrder), f'Unexpected order type: {order}')
            trade_price = 0.5 * (o + h) if order.qty > 0 else 0.5 * (o + l)

            if np.isnan(trade_price): continue

            trade = pq.Trade(order.contract, order, timestamp, order.qty, trade_price, commission=0, fee=0)
            order.fill()
            _logger.info(f'trade: {trade}')

            trades.append(trade)

        return trades

    def get_price(contract: pq.Contract, 
                  timestamps: np.ndarray, 
                  i: int, 
                  strategy_context: pq.StrategyContextType) -> float:
        if contract.symbol == 'AAPL':
            return strategy_context.aapl_price[i]
        elif contract.symbol == 'IBM':
            return strategy_context.ibm_price[i]
        raise Exception(f'Unknown contract: {contract}')

    pq.Contract.clear_cache()
    pq.ContractGroup.clear_cache()

    aapl_contract_group = pq.ContractGroup.get('AAPL')
    ibm_contract_group = pq.ContractGroup.get('IBM')

    strategy_context = SimpleNamespace(aapl_price=aapl_prices.c.values, ibm_price=ibm_prices.c.values)

    strategy = pq.Strategy(timestamps, [aapl_contract_group, ibm_contract_group], get_price, trade_lag=1, strategy_context=strategy_context)
    for cg, prices in [(aapl_contract_group, aapl_prices), (ibm_contract_group, ibm_prices)]:
        for column in ['o', 'h', 'l', 'c']:
            strategy.add_indicator(column, pq.VectorIndicator(prices[column].values), contract_groups=[cg])

    strategy.add_indicator('ratio', pq.VectorIndicator(ratio.values))
    strategy.add_indicator('zscore', zscore_indicator, depends_on=['ratio'])

    strategy.add_signal('pair_strategy_signal', pair_strategy_signal, depends_on_indicators=['zscore'])

    # ask pqstrat to call our trading rule when the signal has one of the values [-2, -1, 1, 2]
    strategy.add_rule('pair_entry_rule', pair_entry_rule, 
                      signal_name='pair_strategy_signal', sig_true_values=[-2, 2], position_filter='zero')

    strategy.add_rule('pair_exit_rule', pair_exit_rule, 
                      signal_name='pair_strategy_signal', sig_true_values=[-1, 1], position_filter='nonzero')

    strategy.add_market_sim(market_simulator)

    strategy.run_indicators()
    strategy.run_signals()
    strategy.run_rules()

    metrics = strategy.evaluate_returns(plot=False, display_summary=False, return_metrics=True)
    assert metrics is not None
    assert math.isclose(metrics['gmean'], 4.34631, abs_tol=1e-5)
    assert math.isclose(metrics['sharpe'], 3.92153, abs_tol=1e-5)
    assert math.isclose(metrics['mdd_pct'], 0.012193, abs_tol=1e-5)


def test_strategy_2() -> None:
    '''Test of a dummy strategy'''
    
    def test_signal(contract_group: pq.ContractGroup,
                    timestamps: np.ndarray,
                    indicators: SimpleNamespace, 
                    parent_signals: SimpleNamespace,
                    strategy_context: pq.StrategyContextType) -> np.ndarray: 
        return np.full(len(timestamps), True)
    
    def test_rule(contract_group: pq.ContractGroup,
                  i: int,
                  timestamps: np.ndarray,
                  indicators: SimpleNamespace,
                  signal: np.ndarray,
                  account: pq.Account,
                  orders: Sequence[pq.Order],
                  strategy_context: pq.StrategyContextType) -> list[pq.Order]:
        contract = contract_group.get_contract(contract_group.name)
        order = pq.MarketOrder(  # type: ignore
            contract=contract,  # type: ignore
            timestamp=timestamps[i], 
            qty=10, 
            reason_code='ENTER')
        _logger.info(order)
        return [order]
            
    def market_simulator(orders: Sequence[pq.Order],
                         i: int,
                         timestamps: np.ndarray,
                         indicators: dict[str, SimpleNamespace],
                         signals: dict[str, SimpleNamespace],
                         strategy_context: pq.StrategyContextType) -> list[pq.Trade]:
        trades = []
        for order in orders:
            assert order.contract is not None
            trade = pq.Trade(order.contract, order, timestamps[i], order.qty, 50)
            trades.append(trade)
        _logger.info(f'trades: {trades}')
        return trades
    
    def get_price(contract: pq.Contract, timestamps: np.ndarray, i: int, strategy_context: pq.StrategyContextType) -> float:
        return 11
                
    timestamps = np.arange(np.datetime64('2018-01-05T08:00'), np.datetime64('2018-01-05T08:05'))
    prices = np.array([8.9, 8.10, 20, 20.1, 19])
    symbols = ['AAPL', 'AAPL', 'MSFT', 'MSFT', 'MSFT']
    df = pd.DataFrame({'timestamp': timestamps, 'symbol': symbols, 'price': prices})
    
    pq.ContractGroup.clear_cache()
    pq.Contract.clear_cache()
    cgs = []
    for symbol in ['AAPL', 'MSFT']:
        cg = pq.ContractGroup.get(symbol)
        _ = pq.Contract.create(symbol, cg)
        cgs.append(cg)
        # test_cg.add_contract(contract)
    strategy = pq.Strategy(timestamps, cgs, get_price, trade_lag=1)
    for cg in cgs:
        _prices = df.set_index('timestamp').reindex(timestamps)
        strategy.add_indicator('price', pq.VectorIndicator(_prices.price.values), [cg])
    strategy.add_signal('test_sig', test_signal, cgs, ['price'])
    strategy.add_rule('test_rule', test_rule, signal_name='test_sig')

    strategy.add_market_sim(market_simulator)
    strategy.run()
    

if __name__ == '__main__':
    test_strategy()
    test_strategy_2()
# $$_end_code
# $$_markdown
# # 
# $$_end_markdown
