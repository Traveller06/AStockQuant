"""Offline regression checks; deliberately excludes GUI and live network."""
import ast
import gzip
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd

tree = ast.parse(Path(__file__).with_name('main.py').read_text(encoding='utf-8'))
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('entry_rule_signals','enrich_worldquant_factors','evaluate_entry_rules','dual_engine_from_base','strict_sample_gate','load_prepared_history','create_safe_upload_bundle','snapshot_cache_key','save_validation_snapshot','load_validation_snapshot','_snapshot_encode','_snapshot_decode','enrich_entry_quality','portfolio_backtest','adaptive_index_overlay','stability_rank','stratified_research_sample','research_candidate_queue','readable_eta','eastmoney_secid','parse_eastmoney_klines')]
ns = dict(np=np, pd=pd, json=__import__('json'), gzip=gzip, hashlib=__import__('hashlib'), zipfile=zipfile, Path=Path, datetime=datetime, INDUSTRY_MAP={}, ENTRY_RULES=("1 推荐","2 严格","3 折中","4 世坤因子"))
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), ns)
backtest = ns['portfolio_backtest']
enrich = ns['enrich_entry_quality']
overlay = ns['adaptive_index_overlay']
stability_rank = ns['stability_rank']
sample = ns['stratified_research_sample']
candidate_queue = ns['research_candidate_queue']
eta = ns['readable_eta']
eastmoney_id = ns['eastmoney_secid']
parse_em = ns['parse_eastmoney_klines']
entry_signals = ns['entry_rule_signals']
strict_gate = ns['strict_sample_gate']
load_prepared = ns['load_prepared_history']
def _missing_bundle(*args,**kwargs):
    raise AssertionError('create_safe_upload_bundle 尚未实现')
create_bundle = ns.get('create_safe_upload_bundle',_missing_bundle)
snapshot_key = ns.get('snapshot_cache_key',_missing_bundle)
save_snapshot = ns.get('save_validation_snapshot',_missing_bundle)
load_snapshot = ns.get('load_validation_snapshot',_missing_bundle)
enrich_factors = ns.get('enrich_worldquant_factors',_missing_bundle)
evaluate_rules = ns.get('evaluate_entry_rules',_missing_bundle)
from_stock_base = ns.get('dual_engine_from_base',_missing_bundle)

def frame(n=4):
    f = pd.DataFrame(index=pd.bdate_range('2024-01-05', periods=n))
    for k,v in dict(open=10.,close=10.,high=10.5,low=9.5,ma20=9.5,week_end=False,
                    week_trend=False,week_exit=False,week_exit_ma10=False,
                    week_exit_confirm2=False,week_exit_ma5=False,above_ma=False,engulf=False,
                    volume_ok=True,stop_ref=9.,signal_score=1.).items(): f[k]=v
    f.loc[f.index[0], ['week_end','week_trend','above_ma','engulf']] = True
    return f

def run(frames):
    return backtest(frames, {'关闭':{}}, evaluation_start='2024-01-01', max_positions=8)

class ExecutionTests(unittest.TestCase):
    def test_worldquant_factor_scores_are_cross_sectional_and_causal(self):
        idx=pd.bdate_range('2023-01-02',periods=90)
        frames={}
        for n,code in enumerate(('000001','000002','600000')):
            trend=np.linspace(10+n,18+n*(2-n),len(idx))
            wave=np.sin(np.arange(len(idx))/(4+n))*.3
            close=trend+wave
            frames[code]=pd.DataFrame({
                'open':close*(.997+n*.001),'close':close,
                'high':close*1.02,'low':close*.98,
                'volume':1000+np.arange(len(idx))*(5+n)+np.cos(np.arange(len(idx))/3)*40,
            },index=idx)
        scored=enrich_factors(frames)
        expected={'wq_momentum20','wq_reversal5','wq_price_volume_corr10','wq_range_position20',
                  'wq_low_volatility20','wq_volume_impulse5','worldquant_score'}
        self.assertTrue(expected.issubset(scored['000001'].columns))
        final_scores=[float(scored[c].loc[idx[-1],'worldquant_score']) for c in frames]
        self.assertTrue(all(np.isfinite(final_scores)))
        self.assertTrue(all(0<=value<=100 for value in final_scores))
        changed={code:value.copy() for code,value in frames.items()}
        changed['000001'].loc[idx[70]:,['open','close','high','low']]*=4
        changed['000001'].loc[idx[70]:,'volume']*=7
        revised=enrich_factors(changed)
        for code in frames:
            pd.testing.assert_series_equal(
                scored[code].loc[:idx[69],'worldquant_score'],
                revised[code].loc[:idx[69],'worldquant_score'])

    def test_worldquant_rule_ranks_higher_composite_first(self):
        low=frame(5); high=frame(5)
        low['worldquant_score']=10.; high['worldquant_score']=90.
        low['wq_momentum20']=.1; high['wq_momentum20']=.9
        low.loc[low.index[0],'signal_score']=100.
        high.loc[high.index[0],'signal_score']=1.
        _,trades,_=backtest({'000001':low,'000002':high},{'关闭':{}},evaluation_start='2024-01-01',max_positions=1,entry_rule='4 世坤因子')
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]['code'],'000002')
        self.assertEqual(trades[0]['worldquant_score'],90.)

    def test_entry_rule_comparison_covers_all_four_rules(self):
        old=frame(5); old.index=pd.bdate_range('2023-01-02',periods=5)
        new=frame(5); new.index=pd.bdate_range('2024-01-02',periods=5)
        combined=pd.concat([old,new]); combined['worldquant_score']=75.
        result=evaluate_rules({'000001':combined},{'关闭':{}},100000,[2023],'2024-01-01')
        self.assertEqual([row['入场规则'] for row in result['summary']],
                         ['1 推荐','2 严格','3 折中','4 世坤因子'])
        self.assertEqual(len(result['annual']),4)
        self.assertEqual(set(result['cache']),{
            ('1 推荐','2023'),('1 推荐','forward'),('2 严格','2023'),('2 严格','forward'),
            ('3 折中','2023'),('3 折中','forward'),('4 世坤因子','2023'),('4 世坤因子','forward')})

    def test_index_sleeves_reuse_the_stock_base_without_changing_trades(self):
        f=frame(5)
        base,trades,stock_stats=backtest({'000001':f},{'关闭':{}},evaluation_start='2024-01-01',max_positions=8)
        idx=pd.bdate_range('2023-01-02',periods=300)
        market=pd.DataFrame({'close':np.linspace(100,160,len(idx))},index=idx)
        curve,returned,events,stats=from_stock_base(base,trades,stock_stats,market,market,100000,20)
        self.assertIs(returned,trades)
        self.assertEqual(stats['交易次数'],stock_stats['交易次数'])
        self.assertEqual(curve.index.tolist(),base.index.tolist())
        self.assertIn('stock_cash',curve.columns)

    def test_validation_snapshot_round_trip_and_cache_invalidation(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); cache=root/'cache'; cache.mkdir()
            (cache/'600000.csv').write_text('date,close\n2024-01-01,10\n',encoding='utf-8')
            (cache/'000001.csv').write_text('date,close\n2024-01-01,12\n',encoding='utf-8')
            config={'start_year':2018,'validation_year':2024,'initial':100000,'entry_rule':'1 推荐','strict':True}
            key=snapshot_key(['600000','000001'],config,cache,'engine-1')
            reversed_key=snapshot_key(['000001','600000'],config,cache,'engine-1')
            self.assertNotEqual(key,reversed_key)
            idx=pd.date_range('2024-01-01',periods=2)
            payload={'curves':{'纯股票':pd.DataFrame({'equity':[100000.,100100.]},index=idx)},
                     'benchmark':pd.Series([100000.,100200.],index=idx,name='benchmark'),
                     'rows':[{'收益':np.float64(0.1)}],'created':pd.Timestamp('2024-01-02')}
            target=root/'validation_snapshot.json.gz'
            save_snapshot(target,payload,key)
            restored=load_snapshot(target,key)
            pd.testing.assert_frame_equal(restored['curves']['纯股票'],payload['curves']['纯股票'],check_freq=False)
            pd.testing.assert_series_equal(restored['benchmark'],payload['benchmark'],check_freq=False)
            self.assertEqual(restored['created'],payload['created'])
            (cache/'600000.csv').write_text('date,close\n2024-01-01,11\n',encoding='utf-8')
            changed=snapshot_key(['600000','000001'],config,cache,'engine-1')
            self.assertNotEqual(key,changed)
            with self.assertRaisesRegex(ValueError,'快照条件已变化'):
                load_snapshot(target,changed)

    def test_upload_bundle_includes_audit_files_and_excludes_account_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            audit=root/'dual_engine_validation_v7_3_2.csv'; audit.write_text('收益率\n0.93\n',encoding='utf-8')
            sample_file=root/'research_sample.json'; sample_file.write_text('{"qualified":true}',encoding='utf-8')
            account=root/'paper_account.json'; account.write_text('{"cash":100000}',encoding='utf-8')
            target=root/'AStockQuant核实上传包.zip'
            included=create_bundle(target,[audit,sample_file,account])
            self.assertEqual(set(included),{audit.name,sample_file.name})
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(set(archive.namelist()),{audit.name,sample_file.name})
                self.assertNotIn('paper_account.json',archive.namelist())

    def test_prepared_history_accepts_stock_listed_after_research_start(self):
        with tempfile.TemporaryDirectory() as folder:
            old_cache_dir=load_prepared.__globals__.get('CACHE_DIR')
            load_prepared.__globals__['CACHE_DIR']=Path(folder)
            try:
                dates=pd.bdate_range('2019-07-22',periods=300)
                data=pd.DataFrame({
                    'date':dates,'open':10.,'close':10.1,'high':10.2,'low':9.9,'volume':1000.
                })
                data.to_csv(Path(folder)/'688001.csv',index=False)
                loaded=load_prepared('688001',2018)
                self.assertEqual(len(loaded),300)
                self.assertEqual(loaded.index.min().year,2019)
            finally:
                load_prepared.__globals__['CACHE_DIR']=old_cache_dir

    def test_rule_1_enters_without_volume_and_marks_confirmation(self):
        f=frame(); f['volume_ok']=False
        signals=entry_signals(f,'1 推荐')
        self.assertTrue(bool(signals.entry_signal.iloc[0]))
        self.assertEqual(signals.entry_confirmation.iloc[0],'买入观察')
        f.loc[f.index[0],'volume_ok']=True
        signals=entry_signals(f,'1 推荐')
        self.assertEqual(signals.entry_confirmation.iloc[0],'强确认')

    def test_rule_2_requires_same_day_volume(self):
        f=frame(); f['volume_ok']=False
        self.assertFalse(bool(entry_signals(f,'2 严格').entry_signal.iloc[0]))
        f.loc[f.index[0],'volume_ok']=True
        self.assertTrue(bool(entry_signals(f,'2 严格').entry_signal.iloc[0]))

    def test_rule_3_waits_for_observed_volume_without_lookahead(self):
        f=frame(6); f[['above_ma','engulf','volume_ok']]=False
        f.loc[f.index[0],['above_ma','engulf']]=True
        before=entry_signals(f,'3 折中')
        self.assertFalse(before.entry_signal.any())
        f.loc[f.index[3],'volume_ok']=True
        after=entry_signals(f,'3 折中')
        self.assertFalse(after.entry_signal.iloc[:3].any())
        self.assertTrue(bool(after.entry_signal.iloc[3]))

    def test_strict_300_gate_requires_exact_same_unique_universe(self):
        codes=[f'{i:06d}' for i in range(300)]
        payload={'qualified':True,'target_success':300,'stocks':[{'代码':c} for c in codes]}
        counts=strict_gate(codes,payload,codes)
        self.assertEqual(counts,{'输入代码':300,'准备样本':300,'信号成功':300})
        with self.assertRaisesRegex(ValueError,'信号成功299/300'):
            strict_gate(codes,payload,codes[:-1])
        with self.assertRaisesRegex(ValueError,'界面股票池与准备样本不一致'):
            strict_gate(codes[:-1]+['999999'],payload)

    def test_backtest_records_entry_rule_and_daily_ledger(self):
        f=frame(); f['volume_ok']=False
        curve,trades,_=backtest({'000001':f},{'关闭':{}},evaluation_start='2024-01-01',max_positions=8,entry_rule='1 推荐')
        self.assertEqual(trades[0]['entry_rule'],'1 推荐')
        self.assertEqual(trades[0]['entry_confirmation'],'买入观察')
        self.assertTrue({'cash','position_count'}.issubset(curve.columns))

    def test_multisource_code_routing_and_parse(self):
        self.assertEqual(eastmoney_id('600000'),'1.600000')
        self.assertEqual(eastmoney_id('000001'),'0.000001')
        self.assertEqual(eastmoney_id('920001'),'0.920001')
        row=parse_em(['2024-01-02,10,11,12,9,12345'])
        self.assertEqual(list(row.columns),['date','open','close','high','low','volume'])
        self.assertEqual(row.iloc[0]['close'],'11')

    def test_stratified_sample_rotates_boards(self):
        stocks=[{'code':c} for c in ('600001','600002','000001','000002','300001','688001','800001')]
        chosen=sample(stocks,5)
        self.assertEqual([x['code'] for x in chosen],['600001','000001','300001','688001','800001'])

    def test_failed_primary_has_deterministic_reserve(self):
        stocks=[{'code':c} for c in ('600001','600002','000001','000002','300001','300002')]
        queue,primary=candidate_queue(stocks,3)
        self.assertEqual(len(primary),3)
        self.assertEqual(len(queue),len(stocks))
        self.assertTrue(all(x['code'] in primary for x in queue[:3]))
        self.assertTrue(all(x['code'] not in primary for x in queue[3:]))

    def test_eta_format(self):
        self.assertEqual(eta(59),'59秒'); self.assertEqual(eta(61),'1分1秒'); self.assertEqual(eta(3660),'1小时1分')

    def test_stability_rank_protects_worst_year(self):
        stable=[{'总收益率':x,'最大回撤':-2} for x in (2,2,2,2,2,2)]
        volatile=[{'总收益率':x,'最大回撤':-8} for x in (-5,10,10,10,10,10)]
        self.assertGreater(stability_rank(stable)[1],stability_rank(volatile)[1])

    def test_index_overlay_uses_lagged_state(self):
        idx=pd.bdate_range('2020-01-01',periods=260)
        base=pd.DataFrame({'equity':100000.,'exposure':0.},index=idx)
        market=pd.DataFrame({'close':np.linspace(100,200,len(idx))},index=idx)
        curve,events,stats=overlay(base,market,100000,20,tradable=market)
        self.assertEqual(curve.index[0],idx[0])
        self.assertEqual(curve.index_exposure.iloc[0],0)
        self.assertGreaterEqual(stats['平均指数仓位'],0)

    def test_entry_quality_filters(self):
        profiles=("原始入场","相对强度","均线斜率","量能确认","质量≥2","质量≥3")
        for profile in profiles:
            f=frame(); f['entry_rs60']=1.; f['entry_ma20_slope10']=1.; f['entry_near_high20']=True; f['entry_volume_ratio20']=1.5; f['entry_quality_score']=4
            _,trades,_=backtest({'000001':f},{'关闭':{}},evaluation_start='2024-01-01',entry_profile=profile)
            self.assertEqual(len(trades),1,profile)
        f=frame(); f['entry_rs60']=-1.; f['entry_ma20_slope10']=-1.; f['entry_near_high20']=False; f['entry_volume_ratio20']=.5; f['entry_quality_score']=0
        for profile in profiles[1:]:
            _,trades,_=backtest({'000001':f},{'关闭':{}},evaluation_start='2024-01-01',entry_profile=profile)
            self.assertEqual(trades,[],profile)

    def test_entry_features_do_not_change_with_future_prices(self):
        idx=pd.bdate_range('2023-01-02',periods=100); raw=pd.DataFrame(index=idx)
        raw['close']=np.linspace(10,20,len(idx)); raw['high']=raw.close*1.01; raw['volume']=np.arange(len(idx))+100.; raw['ma20']=raw.close.rolling(20).mean()
        market=pd.DataFrame({'close':np.linspace(100,120,len(idx))},index=idx)
        original=enrich(raw,market); changed=raw.copy(); changed.loc[idx[90]:,'close']*=3
        changed.loc[idx[90]:,'high']*=3; revised=enrich(changed,market)
        pd.testing.assert_series_equal(original.loc[:idx[89],'entry_quality_score'],revised.loc[:idx[89],'entry_quality_score'])

    def test_each_exit_profile_uses_next_session(self):
        profiles={"原规则":"week_exit","跌破10周线":"week_exit_ma10",
                  "连续两周确认":"week_exit_confirm2","5周线拐头":"week_exit_ma5"}
        for profile,column in profiles.items():
            f=frame(); f.loc[f.index[2],['week_end',column]]=[True,True]
            _,trades,_=backtest({'000001':f},{'关闭':{}},evaluation_start='2024-01-01',exit_profile=profile)
            self.assertEqual(trades[0]['sell_date'],f.index[3])
            self.assertEqual(trades[0]['reason'],profile)
        f=frame(); f.loc[f.index[2],'close']=9.; f.loc[f.index[2],'ma20']=9.5
        _,trades,_=backtest({'000001':f},{'关闭':{}},evaluation_start='2024-01-01',exit_profile='跌破20日线')
        self.assertEqual(trades[0]['sell_date'],f.index[3])
        self.assertEqual(trades[0]['reason'],'跌破20日线')

    def test_no_signal(self):
        f=frame(); f['engulf']=False
        c,t,s=run({'000001':f})
        self.assertEqual(t,[]); self.assertEqual(s['期末资产'],100000)

    def test_t_plus_one(self):
        f=frame(); f.loc[f.index[1:3],'low']=8
        c,t,s=run({'000001':f})
        self.assertEqual(len(t),1)
        self.assertEqual(t[0]['buy_date'],f.index[1])
        self.assertEqual(t[0]['sell_date'],f.index[2])
        self.assertFalse(t[0]['same_day_exit'])
        self.assertAlmostEqual(s['期末资产'],100000+t[0]['pnl'])

    def test_final_day_purchase_marked_not_sold(self):
        c,t,s=run({'000001':frame(2)})
        self.assertEqual(t,[])
        self.assertGreater(c.exposure.iloc[-1],0)
        self.assertLess(s['期末资产'],100000)

    def test_invalid_stop_rejected(self):
        f=frame(); f['stop_ref']=11
        c,t,s=run({'000001':f})
        self.assertEqual(t,[]); self.assertEqual(s['期末资产'],100000)

    def test_open_size_independent_of_close(self):
        a=frame(5); b=frame(5)
        b.loc[b.index[0],['week_end','week_trend','above_ma','engulf']]=False
        b.loc[b.index[1],['week_end','week_trend','above_ma','engulf']]=True
        _,trades,_=run({'000001':a,'000002':b})
        changed=a.copy(); changed.loc[changed.index[2],'close']=100
        _,other,_=run({'000001':changed,'000002':b})
        self.assertEqual(next(t['shares'] for t in trades if t['code']=='000002'),
                         next(t['shares'] for t in other if t['code']=='000002'))

if __name__=='__main__': unittest.main()
