import pandas as pd
import numpy as np
import math
import UNI_v3_funcs
import copy

class ActivelyRebalancedStrategy:  
    
    
    def __init__(self, 
                 base_order_width, 
                 base_order_width_large, 
                 limit_order_width, 
                 limit_order_width_large, 
                 alpha, 
                 alpha_large):    
    
        self.base_order_width, self.base_order_width_large = base_order_width, base_order_width_large
        self.limit_order_width, self.limit_order_width_large = limit_order_width, limit_order_width_large
        self.alpha, self.alpha_large = alpha, alpha_large     
        self.signals = pd.read_csv("signals.csv")
        self.signals['date'] = pd.to_datetime(self.signals['date'], utc=True) + pd.DateOffset(hours=1)
        self.lastCheck = None
        self.lastSignal = 0
                
            
    def check_strategy(self,current_strat_obs):

        IsNewHour = (self.lastCheck is None) or (self.lastCheck.hour != current_strat_obs.time.hour)
        LEFT_RANGE_LOW      = current_strat_obs.price < current_strat_obs.strategy_info['reset_range_lower']
        LEFT_RANGE_HIGH     = current_strat_obs.price > current_strat_obs.strategy_info['reset_range_upper']        
        SignalChanged = False
        if IsNewHour :            
            #latestSig = self.signals.iloc[self.signals['date'].searchsorted(current_strat_obs.time)]['signal']
            try :
                latestSig = self.signals.iloc[self.signals['date'].searchsorted(current_strat_obs.time)]['signal']
            except:
                print("  signal not found for %s, default to sig=0"%current_strat_obs.time)
                latestSig = 0
            
            SignalChanged = self.lastSignal != latestSig
            self.lastSignal = latestSig
            self.lastCheck = current_strat_obs.time            
                    
        # if a reset is necessary
        if SignalChanged or LEFT_RANGE_LOW or LEFT_RANGE_HIGH:
            current_strat_obs.reset_point = True                                    
            if SignalChanged : current_strat_obs.reset_reason = 'new signal'
            if LEFT_RANGE_LOW or LEFT_RANGE_HIGH : current_strat_obs.reset_reason = 'leave range'
            # Remove liquidity and claim fees 
            current_strat_obs.remove_liquidity()
            # set ranges
            liq_range,strategy_info = self.set_liquidity_ranges(current_strat_obs, self.lastSignal)
            return liq_range,strategy_info
        else:
            return current_strat_obs.liquidity_ranges,current_strat_obs.strategy_info
    
        
    def get_TICK_AB_for_range(self, order_range_lower, order_range_upper, current_strat_obs):
        TICK_A_PRE         = int(math.log(current_strat_obs.decimal_adjustment * order_range_lower,1.0001))
        TICK_A             = int(round(TICK_A_PRE/current_strat_obs.tickSpacing)*current_strat_obs.tickSpacing)
        TICK_B_PRE        = int(math.log(current_strat_obs.decimal_adjustment * order_range_upper,1.0001))
        TICK_B            = int(round(TICK_B_PRE/current_strat_obs.tickSpacing)*current_strat_obs.tickSpacing)
        if TICK_A==TICK_B: TICK_B=TICK_A+1
        return TICK_A, TICK_B
          
    def set_liquidity_ranges(self,current_strat_obs, latestSig = 0):
                
        is_init = False
        if current_strat_obs.strategy_info is None:
            strategy_info_here = dict()
            is_init = True
        else:
            strategy_info_here = copy.deepcopy(current_strat_obs.strategy_info)       
            
        ########################################################### 
        # Set reset range
        ###########################################################
        strategy_info_here['reset_range_mid'] = current_strat_obs.price
        
        if latestSig < 0 :
            # we want to accumulate token_0, and reduce token_1
            strategy_info_here['reset_range_lower']     = 1 / (1 + self.alpha) * strategy_info_here['reset_range_mid']
            strategy_info_here['reset_range_upper']     = (1 + self.alpha_large) * strategy_info_here['reset_range_mid']
        elif latestSig > 0 :
            # we want to reduce token_0, an accumulate token_1
            strategy_info_here['reset_range_lower']     = 1 / (1 + self.alpha_large) * strategy_info_here['reset_range_mid']
            strategy_info_here['reset_range_upper']     = (1 + self.alpha) * strategy_info_here['reset_range_mid']
        else : # latestSig == 0
            strategy_info_here['reset_range_lower']     = 1 / (1 + self.alpha) * strategy_info_here['reset_range_mid']
            strategy_info_here['reset_range_upper']     = (1 + self.alpha) * strategy_info_here['reset_range_mid']
        
        save_ranges                = []
        
        ########################################################### 
        # ORDER 1: Base order
        ###########################################################
                
        if latestSig < 0 :
            # we want to accumulate token_0, and reduce token_1
            order1_range_lower = 1 / (1 + self.base_order_width) * current_strat_obs.price
            order1_range_upper = (1 + self.base_order_width_large) * current_strat_obs.price
        elif latestSig > 0 :
            # we want to reduce token_0, an accumulate token_1
            order1_range_lower = 1 / (1 + self.base_order_width_large) * current_strat_obs.price
            order1_range_upper = (1 + self.base_order_width) * current_strat_obs.price
        else : # latestSig == 0
            order1_range_lower = 1/ (1 + self.base_order_width) * current_strat_obs.price
            order1_range_upper = (1 + self.base_order_width) * current_strat_obs.price
        
        total_token_0_amount = current_strat_obs.liquidity_in_0
        total_token_1_amount = current_strat_obs.liquidity_in_1
                    
        TICK_A, TICK_B = self.get_TICK_AB_for_range(order1_range_lower, order1_range_upper, current_strat_obs)
        liquidity_placed_order1         = int(UNI_v3_funcs.get_liquidity(current_strat_obs.price_tick,TICK_A,TICK_B,
                                                    current_strat_obs.liquidity_in_0, current_strat_obs.liquidity_in_1,  
                                                    current_strat_obs.decimals_0,current_strat_obs.decimals_1))
        
        order1_0_amount, order1_1_amount   = UNI_v3_funcs.get_amounts(current_strat_obs.price_tick,TICK_A,TICK_B,liquidity_placed_order1,
                                                    current_strat_obs.decimals_0,current_strat_obs.decimals_1)                
            
        total_token_0_amount  -= order1_0_amount
        total_token_1_amount  -= order1_1_amount

        order1_range =        {'price'              : current_strat_obs.price,
                                'lower_bin_tick'     : TICK_A,
                                'upper_bin_tick'     : TICK_B,
                                'lower_bin_price'    : order1_range_lower,
                                'upper_bin_price'    : order1_range_upper,
                                'time'               : current_strat_obs.time,
                                'token_0'            : order1_0_amount,
                                'token_1'            : order1_1_amount,
                                'position_liquidity' : liquidity_placed_order1,
                                'reset_time'         : current_strat_obs.time}

        save_ranges.append(order1_range)
        
        ########################################################### 
        # ORDER 1: Limit order
        ###########################################################                
        
        strategy_info_here['latestSig']     = latestSig
        
        limit_amount_0 = total_token_0_amount
        limit_amount_1 = total_token_1_amount
        
        if limit_amount_0*current_strat_obs.price > limit_amount_1:        
            # Place Token 0 limit order
            limit_amount_1 = 0.0
            order2_range_lower = current_strat_obs.price 
            if latestSig < 0 :
                # we want to accumulate token_0. so we make the token_0 limit order width large             
                limit_order_width = self.limit_order_width_large
            elif latestSig > 0 :
                # we want to reduce token_0. so we make the token_0 limit order width small             
                limit_order_width = self.limit_order_width
            else : # latestSig == 0
                limit_order_width = self.limit_order_width
            order2_range_upper = (1 + limit_order_width) * current_strat_obs.price    
            TICK_A, TICK_B = self.get_TICK_AB_for_range(order2_range_lower, order2_range_upper, current_strat_obs)
            while TICK_A <= current_strat_obs.price_tick :
                TICK_A, TICK_B = TICK_A+1 , TICK_B+1
        else:
            # Place Token 1 limit order
            limit_amount_0 = 0.0            
            order2_range_upper = current_strat_obs.price 
            if latestSig < 0 :
                # we want to reduce token_1. so we make the token_1 limit order width small             
                limit_order_width = self.limit_order_width
            elif latestSig > 0 :
                # we want to accumulate token_1. so we make the token_1 limit order width large             
                limit_order_width = self.limit_order_width_large
            else : # latestSig == 0
                limit_order_width = self.limit_order_width
            order2_range_lower = 1 / (1 + limit_order_width) * current_strat_obs.price    
            TICK_A, TICK_B = self.get_TICK_AB_for_range(order2_range_lower, order2_range_upper, current_strat_obs)
            while TICK_B >= current_strat_obs.price_tick :
                    TICK_A, TICK_B = TICK_A-1 , TICK_B-1
        
        liquidity_placed_order2        = int(UNI_v3_funcs.get_liquidity(current_strat_obs.price_tick,TICK_A,TICK_B, 
                                                    limit_amount_0, limit_amount_1, current_strat_obs.decimals_0,current_strat_obs.decimals_1))        

        order2_0_amount, order2_1_amount =     UNI_v3_funcs.get_amounts(current_strat_obs.price_tick, TICK_A, TICK_B,
                                                    liquidity_placed_order2,current_strat_obs.decimals_0,current_strat_obs.decimals_1)      
        
        order2_range =          {'price'              : current_strat_obs.price,
                                 'lower_bin_tick'     : TICK_A,
                                 'upper_bin_tick'     : TICK_B,
                                 'lower_bin_price'    : order2_range_lower,
                                 'upper_bin_price'    : order2_range_upper,                                 
                                 'time'               : current_strat_obs.time,
                                 'token_0'            : order2_0_amount,
                                 'token_1'            : order2_1_amount,
                                 'position_liquidity' : liquidity_placed_order2,
                                 'reset_time'         : current_strat_obs.time}     

        save_ranges.append(order2_range)        
        
        total_token_0_amount  -= order2_0_amount
        total_token_1_amount  -= order2_1_amount
        
        # How much liquidity is not allcated to ranges
        current_strat_obs.token_0_left_over = max([total_token_0_amount,0.0])
        current_strat_obs.token_1_left_over = max([total_token_1_amount,0.0])

        # Since liquidity was allocated, set to 0
        current_strat_obs.liquidity_in_0 = 0.0
        current_strat_obs.liquidity_in_1 = 0.0
        
        return save_ranges,strategy_info_here
        
        
    ########################################################
    # Extract strategy parameters
    ########################################################
    def dict_components(self,strategy_observation):
            this_data = dict()
            
            # General variables
            this_data['time']                   = strategy_observation.time
            this_data['price']                  = strategy_observation.price
            this_data['reset_point']            = strategy_observation.reset_point
            this_data['reset_reason']           = strategy_observation.reset_reason
            
            # Range Variables
            this_data['base_range_lower']       = strategy_observation.liquidity_ranges[0]['lower_bin_price']
            this_data['base_range_upper']       = strategy_observation.liquidity_ranges[0]['upper_bin_price']
        
            this_data['limit_range_lower']      = strategy_observation.liquidity_ranges[1]['lower_bin_price']
            this_data['limit_range_upper']      = strategy_observation.liquidity_ranges[1]['upper_bin_price']
            
            this_data['reset_range_lower']      = strategy_observation.strategy_info['reset_range_lower']
            this_data['reset_range_upper']      = strategy_observation.strategy_info['reset_range_upper']
            this_data['latestSig']              = strategy_observation.strategy_info['latestSig']
            this_data['price_at_reset']         = strategy_observation.liquidity_ranges[0]['price']
            
            # Fee Varaibles
            this_data['token_0_fees']           = strategy_observation.token_0_fees 
            this_data['token_1_fees']           = strategy_observation.token_1_fees 
            this_data['token_0_fees_uncollected']     = strategy_observation.token_0_fees_uncollected
            this_data['token_1_fees_uncollected']     = strategy_observation.token_1_fees_uncollected
            
            # Asset Variables
            this_data['token_0_left_over']      = strategy_observation.token_0_left_over
            this_data['token_1_left_over']      = strategy_observation.token_1_left_over
            
            total_token_0 = 0.0
            total_token_1 = 0.0
            for i in range(len(strategy_observation.liquidity_ranges)):
                total_token_0 += strategy_observation.liquidity_ranges[i]['token_0']
                total_token_1 += strategy_observation.liquidity_ranges[i]['token_1']
                
            this_data['token_0_allocated']      = total_token_0
            this_data['token_1_allocated']      = total_token_1
            this_data['token_0_total']          = total_token_0 + strategy_observation.token_0_left_over + strategy_observation.token_0_fees_uncollected
            this_data['token_1_total']          = total_token_1 + strategy_observation.token_1_left_over + strategy_observation.token_1_fees_uncollected

            # Value Variables          
            this_data['value_position_in_token_0']         = this_data['token_0_total']     + this_data['token_1_total']     / this_data['price']
            this_data['value_allocated_in_token_0']        = this_data['token_0_allocated'] + this_data['token_1_allocated'] / this_data['price']
            this_data['value_left_over_in_token_0']        = this_data['token_0_left_over'] + this_data['token_1_left_over'] / this_data['price']
            
            this_data['base_position_value_in_token_0']    = strategy_observation.liquidity_ranges[0]['token_0'] + strategy_observation.liquidity_ranges[0]['token_1'] / this_data['price']
            this_data['limit_position_value_in_token_0']   = strategy_observation.liquidity_ranges[1]['token_0'] + strategy_observation.liquidity_ranges[1]['token_1'] / this_data['price']
             
            return this_data
