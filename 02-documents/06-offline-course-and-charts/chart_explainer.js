/* Plain-language explanations derived only from the supplied chart cutoff. */
(function (root, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  if (root) root.ChanExplain = api;
})(typeof window !== 'undefined' ? window : typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const PERIODS = Object.freeze({
    '1m': { label: '1分钟', role: '看局部细节和触发时点。它的一次转折，不能单独证明大周期反转。' },
    '5m': { label: '5分钟', role: '观察较细的推进与回调。放回更大周期背景，才知道它是调整还是新方向。' },
    '15m': { label: '15分钟', role: '观察日内结构。要先看自己的中枢和线段，再核对更大周期。' },
    '30m': { label: '30分钟', role: '把短期波动组织成较清楚的结构；下级确认仍需要单独的数据和证据。' },
    '60m': { label: '60分钟', role: '观察较慢的短期结构。不能把同一份数据换个名字当成60分钟。' },
    day: { label: '日线', role: '一根表示一个交易日。它适合看交易日之间的结构；盘中信号不能直接冒充日线确认。' },
    week: { label: '周线', role: '一根汇总一周的交易。周线讲的是采样周期，不等于递归结构的L2。' },
    month: { label: '月线', role: '一根汇总一个月的交易。月线历史短时，可能连一笔都还无法确认。' },
    quarter: { label: '季线', role: '一根汇总一个季度。它需要更长历史，数据少就保留未完成状态。' },
    year: { label: '年线', role: '一根汇总一年。只有几根年线时，应讲清样本不足，不能凑出趋势或中枢。' }
  });
  const ALIASES = { daily: 'day', '1d': 'day', d: 'day', weekly: 'week', '1w': 'week', w: 'week', monthly: 'month', '1mo': 'month', quarterly: 'quarter', yearly: 'year', annual: 'year' };
  const SIGNAL_NAMES = {
    first_buy: '一买', second_buy: '二买', third_buy: '三买',
    first_sell: '一卖', second_sell: '二卖', third_sell: '三卖'
  };
  const PATH_NAMES = {
    feature_no_gap: '无缺口特征分型', feature_gap: '缺口后等待第二特征序列',
    feature_gap_second_sequence: '缺口后等待第二特征序列', first_pen_break: '笔破坏后的进一步结构确认'
  };
  const STATE_NAMES = {
    formed: '中枢刚形成', extended: '中枢延伸', extension: '中枢延伸', leaving: '正在离开中枢',
    departed: '已经离开中枢', broken: '离开后回试不返回', partition_cut: '同级分解切分',
    confirmed: '已取得规则依据', provisional: '尚未完成', complete: '分解单元完成',
    invalidated: '已经失效', withdrawn: '已经撤回', stale_on_confirmation: '确认时已经失效',
    awaiting_lower_confirmation: '等待下级结构确认', waiting_lower_confirmation: '等待下级结构确认',
    waiting_trigger: '等待更细级触发', structurally_triggered_under_profile: '按当前规则获得结构触发',
    candidate: '仍是观察候选', trend_divergence_supported_candidate: '趋势背驰候选具备当前证据',
    trend_force_weakening_observed: '趋势内力度减弱', consolidation_force_weakening: '盘整内力度减弱',
    not_supported: '背驰条件不足', developing: '结构仍在发展', expansion_pending: '扩展待确认',
    insufficient_children: '下级组件不足', unresolved_prefix: '前段结构尚不明确'
  };

  const arr = x => Array.isArray(x) ? x : [];
  const isNumber = x => typeof x === 'number' && Number.isFinite(x);
  const indexValue = x => Number.isInteger(x) && x >= 0 ? x : null;
  const nfmt = x => isNumber(x) ? Number(x.toFixed(4)).toString() : '未提供';
  const ordinal = x => indexValue(x) === null ? '尚未确认' : `第${x + 1}根`;
  const stateName = s => STATE_NAMES[s] || (s ? String(s) : '尚未确认');
  const codeClass = p => String(p.class || p.native_class || p.signal_class || '').replace(/_candidate$/, '');
  const safeId = x => x == null ? '' : String(x);
  const unique = values => [...new Set(values)];
  const last = values => values.length ? values[values.length - 1] : null;
  const timeAt = (bars, i) => {
    if (indexValue(i) === null || !bars[i]) return ordinal(i);
    const raw = bars[i].closed_at ?? bars[i].time ?? bars[i].timestamp ?? bars[i].date;
    return raw == null || String(raw) === String(i) ? ordinal(i) : `${ordinal(i)}（${String(raw).replace('T', ' ')}）`;
  };
  const objectStart = obj => indexValue(obj.start ?? obj.source_index ?? obj.source ?? obj.anchor ?? obj.group_start);
  const objectEnd = obj => indexValue(obj.end ?? obj.source_index ?? obj.source ?? obj.anchor ?? obj.group_end);
  const knownAt = obj => indexValue(obj.available_at ?? obj.completed_at ?? obj.formed_at ?? obj.basis_at ?? obj.confirmed_at);
  function periodInfo(value) {
    const raw = String(value || '未指定周期');
    const key = ALIASES[raw] || raw;
    return { key, label: PERIODS[key]?.label || raw, role: PERIODS[key]?.role || '当前输入周期未列入常用预设，需以数据来源和收盘时间解释，不能套用分钟倍数。' };
  }
  function parseDate(value) {
    if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\d/.test(value)) return null;
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function reportIndex(report) {
    if (indexValue(report.as_of_index) !== null) return report.as_of_index;
    if (indexValue(report.as_of) !== null) return report.as_of;
    const count = report.input_count ?? report.input_bars ?? report.input_audit?.bars_used;
    return Number.isInteger(count) && count >= 1 ? count - 1 : null;
  }
  function cutoffIndex(context, bars, report) {
    const value = context.as_of;
    if (Number.isInteger(value) && value < 0) return -1;
    if (indexValue(value) !== null) return Math.min(value, bars.length ? bars.length - 1 : value);
    const target = parseDate(value);
    if (target !== null && bars.length) {
      let index = -1;
      for (let i = 0; i < bars.length; i++) {
        const when = parseDate(bars[i].closed_at ?? bars[i].time ?? bars[i].timestamp ?? bars[i].date);
        if (when !== null && when <= target) index = i;
      }
      return index;
    }
    return reportIndex(report) ?? bars.length - 1;
  }
  function visible(obj, cutoff) {
    if (!obj || typeof obj !== 'object') return false;
    const at = knownAt(obj), end = objectEnd(obj);
    return !(at !== null && at > cutoff) && !(end !== null && end > cutoff);
  }
  function filterList(values, cutoff) { return arr(values).filter(obj => visible(obj, cutoff)); }
  function rankOf(obj) { return Number.isInteger(obj.rank) ? obj.rank : Number.isInteger(obj.layer) ? obj.layer : null; }
  function selectRank(values, rank) { return rank === null ? values : values.filter(obj => rankOf(obj) === rank); }
  function isFinal(obj) { return obj.finalized === true || obj.state === 'confirmed' || obj.state === 'complete'; }
  function normalizedReport(report, cutoff, requestedRank) {
    const base = report.base || report;
    const levels = arr(report.hierarchy?.levels).map(layer => ({
      ...layer,
      centers: filterList(layer.centers, cutoff),
      partition_centers: filterList(layer.partition_centers, cutoff),
      completed_types: filterList(layer.completed_types, cutoff),
      comparisons: filterList(layer.comparisons, cutoff),
      signals: filterList(layer.signals, cutoff),
      pending: filterList(layer.pending, cutoff),
      movement_views: {
        ...(layer.movement_views || {}),
        completed_types: filterList(layer.movement_views?.completed_types, cutoff),
        pending: filterList(layer.movement_views?.pending, cutoff)
      }
    }));
    const flatCenters = levels.length ? levels.flatMap(l => l.centers) : filterList(report.centers, cutoff);
    const flatTypes = levels.length ? levels.flatMap(l => l.completed_types) : filterList(report.types, cutoff);
    const comparisons = report.divergence_comparisons || report.comparisons || levels.flatMap(l => l.comparisons);
    const signals = report.signals || report.signal_candidates || levels.flatMap(l => l.signals);
    return {
      merged: filterList(base.merged, cutoff),
      mergedCount: indexValue(report.merged_count) ?? arr(base.merged).length,
      fractals: filterList(base.fractals || report.raw_fractals || report.fractals, cutoff),
      strokes: filterList(base.strokes || report.strokes, cutoff),
      segments: filterList(base.segments || report.segments, cutoff),
      centers: selectRank(flatCenters, requestedRank),
      types: selectRank(flatTypes, requestedRank),
      comparisons: selectRank(filterList(comparisons, cutoff), requestedRank),
      signals: selectRank(filterList(signals, cutoff), requestedRank),
      levels,
      availableRanks: unique([0, ...levels.filter(l=>l.centers.length||l.completed_types.length).map(l => l.rank), ...flatCenters.map(rankOf), ...flatTypes.map(rankOf)].filter(x => Number.isInteger(x) && x >= 0)).sort((a,b)=>a-b),
      pending: levels.filter(l => requestedRank === null || l.rank === requestedRank).flatMap(l => [...l.pending, ...l.movement_views.pending]),
      movementViews: levels.filter(l => requestedRank === null || l.rank === requestedRank).flatMap(l => l.movement_views.completed_types)
    };
  }
  function describeObject(kind, object, inputBars) {
    const obj = object || {}, bars = arr(inputBars), rows = [];
    const k = String(kind || obj.structure_kind || obj.kind || '结构对象');
    const ident = safeId(obj.id ?? obj.signal_id);
    const start = objectStart(obj), end = objectEnd(obj);
    const confirmed = Object.prototype.hasOwnProperty.call(obj, 'confirmed_at') ? indexValue(obj.confirmed_at) : indexValue(obj.completed_at ?? obj.basis_at ?? obj.formed_at);
    const available = knownAt(obj);
    const range = start === null ? null : [start, end ?? start];
    let title = k, text;
    if (obj.zd != null && obj.zg != null) {
      title = `${rankOf(obj) === null ? '' : `L${rankOf(obj)} `}中枢`;
      text = `核心重叠区下沿ZD是${nfmt(obj.zd)}，上沿ZG是${nfmt(obj.zg)}。`;
      if (isNumber(obj.dd) && isNumber(obj.gg)) text += `整个构造范围DD/GG是${nfmt(obj.dd)}到${nfmt(obj.gg)}，和核心边界不是一回事。`;
      const children = arr(obj.member_ids || obj.components || obj.seed_ids);
      if (children.length) text += `当前由${children.length}个命名下级组件组成。`;
      if (obj.certificate) text += obj.certificate.sublevel_types_verified ? '下级已完成走势类型的凭据已核对。' : '这一层使用声明的确认线段最低边界，不能称作从更细周期无限递归证明。';
      rows.push({label:'中枢状态',value:stateName(obj.state)});
      if (obj.departure?.boundary != null) rows.push({label:'离开/回试边界',value:nfmt(obj.departure.boundary)});
    } else if (SIGNAL_NAMES[codeClass(obj)]) {
      title = `${rankOf(obj) === null ? '' : `L${rankOf(obj)} `}${SIGNAL_NAMES[codeClass(obj)]}候选`;
      const state = obj.current_status || obj.status || obj.state;
      text = `${title}的价格端点是${nfmt(obj.price)}，${stateName(state)}。`;
      if (obj.invalidation != null) text += `失效边界是${nfmt(obj.invalidation)}。`;
      if (!obj.trigger && obj.lower_level_trigger !== 'confirmed') text += '这不是已成交信号；还要检查下级结构确认与触发。';
      if (obj.first_signal) rows.push({label:'一类点上下文',value:safeId(obj.first_signal)});
      if (obj.center_id) rows.push({label:'参考中枢',value:safeId(obj.center_id)});
      rows.push({label:'状态',value:stateName(state)});
    } else if (obj.completion || obj.completed_at != null || /完成分解|走势类型|type/.test(k)) {
      title = `${rankOf(obj) === null ? '' : `L${rankOf(obj)} `}${obj.kind === 'trend' ? '趋势类型' : '同级分解单元'}`;
      text = `${title}由${arr(obj.components).length}个下级组件组成。`;
      if (obj.completion?.is_turn_confirmation === false || obj.completion?.rule === 'same_level_completed_center_cut_v1') text += '这里的完成表示按固定规则可以向上递归，不等于价格已经反转。';
      else if (obj.completion?.opposite_side || obj.completion?.rule === 'opposite_center_break_completion_v1') text += '这一视图使用反向中枢破坏及完成回试不返回的证据，和普通分解切分分开记录。';
    } else if (obj.confirmation || /线段|segment/.test(k)) {
      title = '特征序列线段';
      const path = obj.confirmation?.path || obj.completion?.path;
      text = isFinal(obj) ? `这条线段已经取得${PATH_NAMES[path] || '当前规则的结构'}依据。` : '这条线段仍在发展，虚线端点可能继续延伸，不能当成已经封闭。';
      if (path) rows.push({label:'确认路径',value:PATH_NAMES[path] || safeId(path)});
      text += '价格终点和取得确认的时间分开记录；后续新证据可以修订划分。';
    } else if (obj.kind === 'top' || obj.kind === 'bottom' || /分型|fractal/.test(k)) {
      const top = obj.kind === 'top' || /顶/.test(k);
      title = top ? '顶分型' : '底分型';
      text = `中间整理K线的高点和低点都${top?'高':'低'}于两侧，才满足${title}的几何条件。局部拐点不直接等于一${top?'卖':'买'}。`;
    } else if (obj.start_price != null && obj.end_price != null || /笔|stroke/.test(k)) {
      title = obj.direction === 'down' ? '向下笔' : '向上笔';
      text = `${title}把有效的相反分型连接起来，端点价格从${nfmt(obj.start_price)}到${nfmt(obj.end_price)}。`;
      text += isFinal(obj) ? '它已按固定笔规则取得确认依据。' : '它仍是未完成末笔，不能把出现时间当成确认时间。';
    } else {
      text = '这是当前时点记录的结构对象。解释要以它的组件、范围和确认时间为依据；没有提供的条件不能补成已确认。';
    }
    if (range) rows.push({label:'价格端点范围',value:`${ordinal(range[0])}到${ordinal(range[1])}`});
    rows.push({label:'确认时间',value:timeAt(bars,confirmed)},{label:'最早可用',value:timeAt(bars,available)});
    if (obj.rank != null) rows.push({label:'结构秩',value:`L${obj.rank}${obj.child_rank != null ? `，输入来自L${obj.child_rank}` : ''}`});
    if (ident) rows.push({label:'对象ID',value:ident});
    if (arr(obj.components).length) rows.push({label:'组件ID',value:obj.components.map(safeId).join('、')});
    text += `确认时间：${ordinal(confirmed)}；最早可用：${ordinal(available)}。`;
    return {title,text,speech:text,rows,objectId:ident,kind:k,range,confirmationIndex:confirmed,availableIndex:available,highlight:range?{start:range[0],end:range[1],price:isNumber(obj.price)?obj.price:undefined}:null};
  }

  function explainFrame(input) {
    const context=input || {}, sourceReport=context.report || {}, bars=arr(context.bars);
    const pi=periodInfo(context.period || sourceReport.period);
    const requestedRank=context.rank == null || context.rank === 'all' ? null : Math.max(0,Math.floor(Number(context.rank)||0));
    const cutoff=cutoffIndex(context,bars,sourceReport),ri=reportIndex(sourceReport);
    const dateCut=parseDate(context.as_of),reportDate=parseDate(sourceReport.as_of);
    const futureReport=(ri!==null && ri>cutoff) || (dateCut!==null && reportDate!==null && reportDate>dateCut);
    const hasReport=!!context.report && typeof context.report==='object';
    const usable=hasReport&&!futureReport&&cutoff>=0;
    const normalized=normalizedReport(usable?sourceReport:{},cutoff,requestedRank);
    const availableRanks=normalized.availableRanks;
    const rankAvailable=requestedRank===null||requestedRank===0||availableRanks.includes(requestedRank);
    const selectedBars=bars.slice(0,Math.max(0,cutoff+1));
    const n=selectedBars.length;
    const rankLabel=requestedRank===null?'全部已有结构层':`L${requestedRank}`;
    const rankRole=requestedRank===null?'同时看当前已经形成的结构层；不同秩分开读，不把它们当成不同分钟周期。':requestedRank===0?'L0是当前数据分辨率上的已确认线段最低边界。它不是0分钟，也不是由时间倍数推出来的。':`L${requestedRank}只接收完整、连续、同秩的L${requestedRank-1}组件；这里的结构秩不是${pi.label}的别名。`;
    const statuses={invalidated:0,withdrawn:0,waiting:0,triggered:0};
    normalized.signals.forEach(signal=>{
      const s=sourceReport.signal_states?.[signal.signal_id||signal.id] || signal.status || signal.state;
      if (s==='invalidated'||s==='stale_on_confirmation') statuses.invalidated++;
      else if (s==='withdrawn') statuses.withdrawn++;
      else if (s==='structurally_triggered_under_profile') statuses.triggered++;
      else statuses.waiting++;
    });
    const sixCounts=Object.fromEntries(Object.keys(SIGNAL_NAMES).map(k=>[k,normalized.signals.filter(s=>codeClass(s)===k).length]));
    const counts={bars:n,merged:normalized.mergedCount,fractals:normalized.fractals.length,strokes:normalized.strokes.length,confirmedStrokes:normalized.strokes.filter(isFinal).length,segments:normalized.segments.length,confirmedSegments:normalized.segments.filter(isFinal).length,centers:normalized.centers.length,types:normalized.types.length,comparisons:normalized.comparisons.length,signals:normalized.signals.length,sixClasses:sixCounts,...statuses};
    const reasons=[];
    let status='ready';
    if(!hasReport){status='no_report';reasons.push('还没有当前周期的计算报告。请先导入对应周期数据或选择已计算的教学快照。');}
    else if(futureReport){status='report_after_cutoff';reasons.push('传入报告晚于当前回放时点。不能从最终图倒推历史，请先用当前前缀重算。');}
    else if(!n||cutoff<0){status='insufficient_history';reasons.push('当前截止时间没有可用K线。');}
    else if(!rankAvailable){status='rank_not_available';reasons.push(`${rankLabel}尚未形成；先等下级完整组件连续出现并满足重叠条件，不能因为选择了该层就画出中枢。`);}
    else if(n<5){status='insufficient_history';reasons.push(`目前只有${n}根K线，历史太短。分型的右侧、有效笔间隔和后续确认仍可能缺失。`);}
    const sourceGroup=context.source_group||sourceReport.source_group||'未标注来源组';
    const origin=context.synthetic===true?'程序合成的教学数据':context.synthetic===false?'用户提供的行情数据':'来源属性未提供的数据';
    const steps=[];
    const add=(key,title,text,kind,objectId)=>steps.push({key,title,text,...(kind?{kind}:{}),...(objectId?{objectId:safeId(objectId)}:{})});
    add('period','先认当前周期',`${pi.label}：${pi.role} 当前显示${n}根K线，截止${ordinal(cutoff)}。这组输入是${origin}。`);
    add('rank','周期和结构层分开看',rankRole);
    if(!usable){
      add('availability','现在缺什么',reasons.join(' ')||'当前时点的结构证据还不够。');
      add('inclusion','先等K线条件齐备','相邻包含要按已知方向处理；方向未知不能用后面的结果倒推。');
      add('fractal','分型要等右侧证据','顶分型要求中间高点和低点都更高；底分型反过来。右侧尚未完成就只记候选。');
      add('stroke','相反分型不一定成笔','还要满足固定的独立K线、间隔和端点规则。');
      add('center','上层不能凭空出现','至少三个连续、完整、同级的下级走势组件有重叠，才讨论上层中枢。');
      add('signal','缺依据就先观察','没有同级走势背景、明确中枢和后续结构，就不贴已确认买卖点标签。');
      add('knowledge','确认晚于价格端点','极值可以先发生，算法较晚才知道。当前解释不使用截止时间以后的报告。');
    }else{
      add('availability','这一层够不够',reasons.length?reasons.join(' '):`当前可用层级为${availableRanks.map(r=>`L${r}`).join('、')}。${sourceReport.certificate_audit?.state==='passed'?'递归组件和区间凭据检查通过，但这不等于走势已反转。':'还要逐对象核对组件和确认时间。'}`);
      const f=last(normalized.fractals),b=last(normalized.strokes),seg=last(normalized.segments);
      add('base','先看分型和笔',`当前知道${counts.fractals}个分型、${counts.strokes}笔，其中${counts.confirmedStrokes}笔已按规则确认。${b&&!isFinal(b)?'末笔仍在发展，不能直接当成已封闭。':'笔的方向来自有效顶底交替，不是指标交叉。'}`,'stroke',b?.id||f?.id);
      const path=seg?.confirmation?.path;
      add('segments','线段怎样取得依据',`${counts.segments}条线段中，${counts.confirmedSegments}条已取得规则依据。${seg?`最近一条${isFinal(seg)?`使用${PATH_NAMES[path]||'声明规则'}确认`:'仍为候选尾部'}。`:'目前还没有完整线段；继续等有效笔和特征序列。'}反向一笔先是警报，不自动等于整段结束。`,'segment',seg?.id);
      const center=last(normalized.centers);
      add('centers','找共同重叠的区域',center?`${rankLabel}目前有${counts.centers}个中枢。最近核心ZD=${nfmt(center.zd)}、ZG=${nfmt(center.zg)}；外沿DD=${nfmt(center.dd)}、GG=${nfmt(center.gg)}。${stateName(center.state)}。核心和外沿要分开。`:`${rankLabel}目前没有已知中枢。先检查下级组件是否完整、连续、同rank，以及前三个区间是否真的重叠；不要用任意三根K线代替。`,'center',center?.id);
      const type=last(normalized.types),move=last(normalized.movementViews);
      add('types','分解完成不等于反转',`${rankLabel}有${counts.types}个完成分解单元。${type?'它们可按固定规范向上递归；完成切分本身不表示市场转向。':'没有完整单元就不向更高层凑结构。'}${move?`另一个反向中枢破坏视图，最近记录为${move.kind==='trend'?'趋势':'盘整'}类型；它的确认依据需单独检查。`:'反向确认还要等待中枢破坏和完成回试不返回的证据。'}`,'type',type?.id);
      const comp=last(normalized.comparisons);
      add('force','先命名比较段，再谈背驰',comp?`这次比较${safeId(comp.a?.unit_id)||'A段'}与${safeId(comp.c?.unit_id)||'C段'}，它们应属于同rank、同方向的已完成走势。MACD面积为${nfmt(comp.a?.macd_area)}与${nfmt(comp.c?.macd_area)}，当前结果：${stateName(comp.state)}。${arr(comp.blocked_gates).length?'仍有'+comp.blocked_gates.length+'道条件未过。':''}指标减弱不是独立反转按钮。`:'当前还没有可命名的同级同向比较。MACD柱变短只能作力度线索，不能跳过走势和中枢背景直接叫背驰。','comparison',comp?.id);
      const firstSignal=last(normalized.signals);
      add('signals','六类点只讲实际发生的',`当前${rankLabel}的候选：${Object.keys(SIGNAL_NAMES).map(k=>`${SIGNAL_NAMES[k]}${sixCounts[k]}个`).join('，')}。${statuses.invalidated?'其中'+statuses.invalidated+'个已失效。':''}${statuses.withdrawn?'有'+statuses.withdrawn+'个已撤回。':''}零表示尚未观测到，不会补造信号。`,'signal',firstSignal?.id||firstSignal?.signal_id);
      add('trigger','下级确认和触发还要分开',statuses.triggered?`报告记录${statuses.triggered}个按本profile完成的结构触发，仍需核对真实下级中枢破坏和确认后的新细级笔。算法不自动执行交易。`:`当前仍有${statuses.waiting}个候选等待后续依据。小周期同方向标签同时出现，不等于下级确认；要验证同价转折、反向中枢破坏与不返回，再等新的细级确认笔。`);
      add('knowledge','最后看“何时才知道”',`本次只讲${ordinal(cutoff)}及以前可用的结构。图中极值可以画回更早位置，但confirmed_at和available_at决定当时是否已经知道；失效和撤回要追加保留。`);
    }
    const overview=!usable?reasons.join(' '):`${pi.label}与${rankLabel}分开判断：当前有${counts.fractals}个分型、${counts.segments}条线段，所选结构层有${counts.centers}个中枢、${counts.types}个完成分解单元、${counts.signals}个买卖点候选。${rankAvailable?'结构确认以当前时点凭据为准。':reasons.join(' ')}`;
    const result={title:`${pi.label} · ${rankLabel}讲解`,subtitle:`截至${ordinal(cutoff)} · ${origin}`,overview,steps,speech:steps.map(s=>`${s.title}。${s.text}`).join('\n'),availability:{status,reasons,availableRanks,requestedRank,throughIndex:cutoff},periodRole:pi.role,rankRole,counts,sourceGroup};
    if(context.selectedObject){const sel=context.selectedObject;result.selected=describeObject(sel.kind||sel.structure_kind,sel.item||sel.object||sel,selectedBars);}
    return result;
  }
  return Object.freeze({explainFrame,describeObject,periodInfo});
});
