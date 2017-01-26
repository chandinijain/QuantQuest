from __future__ import absolute_import, division, print_function, unicode_literals
import pandas as pd
import numpy as np
import auquanToolbox as at

def runSolution(markets, lookback, trading_strategy,verbose=False):
    budget=1000000
    base_index='SPX'
    exchange = 'abcd'
    date_start = '01-01-2010'
    date_end = '31-12-2014'
    logger = at.get_logger()
    json = False

    if at.updateCheck():
        logger.warn('Your version of auquanToolbox is not the most updated.' +
            ' If you are using pip, please use \'pip install -U auquanToolbox\'.' + 
            ' If you downloaded the package, you need to go to https://github.com/Auquan/auquan-toolbox-python'+
            ' to redownload that package.')

    #Verify Settings
    try:
        assert(isinstance(lookback, int)),"Lookback is invalid"
    except AssertionError:
            logger.exception("Lookback is invalid")
            raise

    #Load data for backtest
   
    (back_data, date_range) = at.load_data(exchange, markets, date_start, date_end, lookback, budget, logger)

    budget_curr = budget
    position_curr = None
    margin_curr = None
    cost_to_trade = None

    start_index = -1

    for startDate in pd.date_range(start=date_start, end=date_end, freq='B'):
        if startDate not in date_range:
            logger.info(startDate.strftime('Trading date is a Holiday or data not present :%d %b %Y'))
            continue
        end = date_range.get_loc(startDate)
        if start_index < 0:
            start_index = end

        start = end - lookback
        if start < 0:
            start = 0

        if position_curr is None:
            position_curr = back_data['POSITION'].iloc[end-1]
            margin_curr = back_data['MARGIN'].iloc[end-1]
            cost_to_trade = position_curr*0

        # get order and verify
        lookback_data = {feature: data[start: end] for feature, data in back_data.items()}
        order = trading_strategy(lookback_data)
        try:
            assert((order['SIGNAL'].isin([-1,0,1])).all())
        except AssertionError:
            logger.info("Signal can only be -1(sell), 0(hold) or 1(buy)")
            raise

        # evaluate new position based on order and budget
        try:
            price_curr = back_data['OPEN'].iloc[end].astype(float)
            open_curr = back_data['OPEN'].iloc[end].astype(float)
            close_curr = back_data['CLOSE'].iloc[end].astype(float)
            open_last = back_data['OPEN'].iloc[end-1].astype(float)
            close_last = back_data['CLOSE'].iloc[end-1].astype(float)
            high = back_data['HIGH'].iloc[end - 1].astype(float)
            low = back_data['LOW'].iloc[end - 1].astype(float)
        except ValueError:
            logger.info("Data not formatted properly")
            raise

        slippage = 0*price_curr
        position_last = back_data['POSITION'].iloc[end - 1].astype(int)
        value = budget_curr + margin_curr + (position_last * open_curr).sum()
        if 'WEIGHTS' in order.columns:
            try:
                assert(order['WEIGHTS']>=0).all() 
            except AssertionError:
                logger.info("Please check weights. Weights cannot be negative and should sum to <= 1")
                raise

            if order['WEIGHTS'].sum()>1:
                order['WEIGHTS'] = order['WEIGHTS']/order['WEIGHTS'].sum()

            order['QUANTITY'] = at.getquantity(order, price_curr, slippage,value,position_last, logger)
            trading_costs = True
            base_index = 'SPX'
        else:
            desired_position = order['SIGNAL']
            order['QUANTITY'] = desired_position - position_last
            trading_costs = False
            base_index = False

        order['PRICE'] = 0*order['SIGNAL']

        (position_curr, budget_curr, margin_curr, cost_to_trade) = at.execute_order(order, position_last, slippage, price_curr, budget_curr,margin_curr,logger, trading_costs)

        # set info in back data
        back_data['POSITION'].iloc[end] = position_curr
        back_data['ORDER'].iloc[end] = order['QUANTITY']
        filled_order = position_curr - position_last
        back_data['FILLED_ORDER'].iloc[end] = filled_order

        # calculate pnl
        pnl_curr = (position_curr * (close_curr  - open_curr) + position_last * (open_curr - close_last)) - cost_to_trade
        back_data['DAILY_PNL'].iloc[end] = pnl_curr
        back_data['TOTAL_PNL'].iloc[end] = pnl_curr + back_data['TOTAL_PNL'].iloc[end - 1]

        # available funds
        back_data['FUNDS'].iloc[end] = budget_curr

        #funds used as margin
        back_data['MARGIN'].iloc[end] = -(position_curr[position_curr<0] * close_curr[position_curr<0]).sum()

        #portfolio value
        value_curr = budget_curr + margin_curr + (margin_curr - back_data['MARGIN'].iloc[end]) + (position_curr[position_curr>0] * close_curr[position_curr>0]).sum()
        back_data['VALUE'].iloc[end] = value_curr

        #cost
        back_data['COST TO TRADE'].iloc[end] = cost_to_trade

        #print to STDOUT
        logger.info(date_range[end].strftime('Trading date :%d %b %Y'))
        if verbose:
            s = 'stocks         : %s'%markets+'\n'+\
            'today open     : %s'%open_curr.values+'\n'+\
            'today close    : %s'%close_curr.values+'\n'+\
            'order          : %s'%order['QUANTITY'].values+'\n'+\
            'position       : %s'%position_curr.values+'\n'+\
            'cost to trade  : %0.2f'%cost_to_trade.sum()+'\n'+\
            'Available funds: %0.2f'%budget_curr+'\n'+\
            'Margin funds   : %0.2f'%margin_curr+'\n'+\
            'pnl            : %0.2f'%pnl_curr.sum()+'\n'+\
            'Portfolio Value: %0.2f'%value_curr+'\n'+\
            '------------------------------------'
            logger.info(s)
        
        if 'WEIGHTS' in order.columns and value_curr<=0:
            logger.info('Out of funds. Exiting!')
            break
            
    if 'WEIGHTS' in order.columns:
        logger.info('Final Portfolio Value: %0.2f'%value_curr)
    else:
        budget = 1

    if json:
        if base_index:
            baseline_data = at.baseline(exchange, base_index, date_range, logger)
            return writejson({feature: data[start_index-1: end+1] for feature, data in back_data.items()},budget,{feature: data[start_index-1: end+1] for feature, data in baseline_data.items()}, base_index)
        else:
            return writejson({feature: data[start_index-1: end+1] for feature, data in back_data.items()},budget,{}, base_index)
    else:
        at.writecsv({feature: data[start_index-1: end+1] for feature, data in back_data.items()},budget)

    logger.info('Plotting Results...')

    at.loadgui({feature: data[start_index-1: end+1] for feature, data in back_data.items()}, exchange, base_index, budget,logger)

def writejson(back_data,budget,baseline_data,base_index):

    daily_return = back_data['DAILY_PNL']*100/budget
    total_return = back_data['TOTAL_PNL']*100/budget
    stats = metrics(daily_return, total_return, baseline_data,base_index)
    if base_index:
        k = 'Sharpe Ratio'
    else:
        k = 'Total Pnl'

    d = {'dates':back_data['DAILY_PNL'].index.format(),\
         'daily_pnl':daily_return.sum(axis=1).values.tolist(),\
         'total_pnl':total_return.sum(axis=1).values.tolist(),\
         'stocks':back_data['DAILY_PNL'].columns.tolist(),\
         'stock_pnl':daily_return.values.tolist(),\
         'stock_position':back_data['POSITION'].values.tolist(),\
         'metrics':stats.keys(),\
         'metrics_values':stats.values(),\
         'score':stats[k]}
    return d;
