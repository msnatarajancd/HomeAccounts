// Exact currency-scoped chart aggregates. Only SVG coordinates use floating point.
const E = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
const COLOURS = ['var(--chart)','var(--income)','#a775db','#d59135','#d96484','#559cac','#8a9271','#bd7552'];
let preference = {period:'month', type:'expenses'};
let resizeObserver;

export function toMinor(value, digits = 2) {
  const text = String(value ?? '0');
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match || (match[3] || '').length > digits) throw new Error('A confirmed amount has invalid currency precision.');
  return (match[1] ? -1n : 1n) * BigInt(match[2] + (match[3] || '').padEnd(digits, '0'));
}

export function formatMinor(value, currency, digits = 2) {
  value = BigInt(value);
  const scale = 10n ** BigInt(digits), magnitude = value < 0n ? -value : value;
  return `${currency} ${value < 0n ? '−' : ''}${new Intl.NumberFormat('en-US').format(magnitude / scale)}${digits ? '.' + String(magnitude % scale).padStart(digits, '0') : ''}`;
}

const sum = values => values.reduce((total, value) => total + value, 0n);
const abs = value => value < 0n ? -value : value;
function budgetTotal(rows, digits) {
  if (!rows.length) return null;
  const parents = new Set(rows.filter(row => !row.subcategory).map(row => row.category));
  return sum(rows.filter(row => !row.subcategory || !parents.has(row.category)).map(row => toMinor(row.amount, digits)));
}

export function aggregateOverviewCharts({transactions = [], budgets = [], currency, month, currencyDigits = 2}) {
  if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(month)) throw new Error('Choose a valid reporting month for the charts.');
  if (!Number.isInteger(currencyDigits) || currencyDigits < 0 || currencyDigits > 4) throw new Error('Unsupported chart currency precision.');
  const year = month.slice(0,4), scoped = transactions.filter(row => row.currency === currency && row.date?.startsWith(year + '-') && ['income','expense'].includes(row.type));
  const limits = budgets.filter(row => row.currency === currency && row.period?.startsWith(year + '-'));
  const months = MONTHS.map((label, index) => {
    const key = year + '-' + String(index + 1).padStart(2, '0');
    const rows = scoped.filter(row => row.date.startsWith(key));
    return {key,label,count:rows.length,expenseCount:rows.filter(row=>row.type==='expense').length,
      expenses:sum(rows.filter(row=>row.type==='expense').map(row=>toMinor(row.amount,currencyDigits))),
      income:sum(rows.filter(row=>row.type==='income').map(row=>toMinor(row.amount,currencyDigits))),
      budget:budgetTotal(limits.filter(row=>row.period===key),currencyDigits)};
  });
  const monthly = scoped.filter(row => row.date.startsWith(month));
  const numericYear = Number(year), numericMonth = Number(month.slice(5));
  const leap = numericYear % 4 === 0 && (numericYear % 100 !== 0 || numericYear % 400 === 0);
  const dayCount = [31,leap?29:28,31,30,31,30,31,31,30,31,30,31][numericMonth-1];
  const days = Array.from({length:dayCount}, (_, index) => {
    const key = month + '-' + String(index+1).padStart(2,'0');
    const rows = monthly.filter(row=>row.date===key&&row.type==='expense');
    return {key,label:String(index+1),count:rows.length,expenses:sum(rows.map(row=>toMinor(row.amount,currencyDigits)))};
  });
  function totals(rows, budgetRows) {
    const expenses = rows.filter(row=>row.type==='expense'), categories = new Map();
    for (const row of expenses) categories.set(row.category || 'Uncategorized', (categories.get(row.category || 'Uncategorized') || 0n) + toMinor(row.amount,currencyDigits));
    const spending = sum(expenses.map(row=>toMinor(row.amount,currencyDigits)));
    const income = sum(rows.filter(row=>row.type==='income').map(row=>toMinor(row.amount,currencyDigits)));
    return {count:rows.length,expenseCount:expenses.length,income,expenses:spending,surplus:income-spending,
      budget:budgetRows.length ? sum(months.filter(item=>budgetRows.some(row=>row.period===item.key)).map(item=>item.budget || 0n)) : null,
      budgetMonths:new Set(budgetRows.map(row=>row.period)).size,
      categories:[...categories].map(([label,value])=>({label,value})).sort((a,b)=>a.value===b.value?a.label.localeCompare(b.label):a.value>b.value?-1:1)};
  }
  return {currency,month,year,digits:currencyDigits,days,months,
    monthTotals:totals(monthly,limits.filter(row=>row.period===month)),yearTotals:totals(scoped,limits)};
}

function choices(period) {
  return [['expenses',period==='month'?'Daily expenses':'Monthly expenses'],['budget','Expenses vs budget'],
    ...(period==='year'?[['surplus','Expenses vs savings (recorded surplus)']]:[]),['category','Category split']];
}

function controls(data, period, type) {
  return `<div class="overview-chart-heading"><div><p class="eyebrow">Explore your records</p><h2>Spending patterns</h2><p class="field-hint">${E(data.currency)} only · Choose a view, then inspect exact values or open the records.</p></div><div class="overview-chart-controls"><div class="overview-chart-period" role="group" aria-label="Chart period"><button type="button" data-chart-period="month" aria-pressed="${period==='month'}">Monthly</button><button type="button" data-chart-period="year" aria-pressed="${period==='year'}">Yearly</button></div><label>Chart type<select data-chart-type aria-label="Overview chart type">${choices(period).map(([value,label])=>`<option value="${value}" ${value===type?'selected':''}>${label}</option>`).join('')}</select></label></div></div>`;
}

function recordsHref(data, {period='month', key, category, type='expense'} = {}) {
  const params = new URLSearchParams({currency:data.currency,month:key?.length===7?key:data.month,type});
  if (period==='year' && !key) {params.set('all','1');params.set('column_date',data.year);}
  if (key?.length===10) params.set('column_date',key);
  if (category) params.set('category',category);
  return '/transactions?' + params;
}

function table(headers, rows, caption) {
  return `<details class="overview-chart-data"><summary>View exact chart data</summary><div class="table-wrap"><table><caption>${E(caption)}</caption><thead><tr>${headers.map(header=>`<th scope="col">${E(header)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${row.map(value=>`<td>${value}</td>`).join('')}</tr>`).join('')}</tbody></table></div></details>`;
}

function openLink(href, label='Open records') {return `<a href="${E(href)}" data-chart-href="${E(href)}">${E(label)}</a>`;}

function barChart(data, items, series, title, description) {
  const W=data.chartWidth||760,H=310,left=W<450?62:85,right=14,top=22,bottom=47,pw=W-left-right,ph=H-top-bottom;
  const values=items.flatMap(item=>series.map(series=>item[series.key]).filter(value=>value!==null));
  const upper=values.reduce((largest,value)=>value>largest?value:largest,0n);
  const lower=values.reduce((smallest,value)=>value<smallest?value:smallest,0n);
  const rawRange=upper-lower||10n**BigInt(data.digits),roughStep=(rawRange+3n)/4n;
  let power=1n;while(power*10n<roughStep)power*=10n;
  const step=[1n,2n,5n,10n].map(value=>value*power).find(value=>value>=roughStep);
  const ceil=value=>(value+step-1n)/step*step;
  const max=upper?ceil(upper):lower?0n:ceil(10n**BigInt(data.digits)),min=lower?-ceil(-lower):0n,range=Number(max-min)||1;
  const y=value=>top+Number(max-value)/range*ph,zero=y(0n),band=pw/items.length;
  const labelStep=items.length>16?5:items.length>8&&W<450?2:1;
  const ticks=[];for(let value=min;value<=max;value+=step)ticks.push(value);
  const decimalPlaces=Math.max(0,data.digits-(String(step).match(/0*$/)?.[0].length||0));
  const compact=value=>{
    const number=Number(value)/(10**data.digits);
    return new Intl.NumberFormat('en-US',{notation:Math.abs(number)>=10000?'compact':'standard',maximumFractionDigits:Math.abs(number)>=10000?1:decimalPlaces}).format(number);
  };
  const axes=ticks.map(value=>`<g><line x1="${left}" x2="${W-right}" y1="${y(value)}" y2="${y(value)}" class="overview-chart-grid"/><text x="${left-12}" y="${y(value)+5}" text-anchor="end">${E(compact(value))}</text></g>`).join('');
  const bars=items.map((item,index)=>{
    const barWidth=Math.min(48,band*.74/series.length),gap=series.length>1?3:0,centre=left+band*(index+.5);
    const grouped=series.map((part,partIndex)=>{
      const value=item[part.key];if(value===null||value===0n)return '';
      const height=Math.max(2,Math.abs(y(value)-zero)),x=centre+(partIndex-series.length/2)*barWidth+gap/2;
      const topY=value===0n?zero-1:value>0n?y(value):zero;
      const label=`${item.key || item.label} · ${part.label}: ${formatMinor(value,data.currency,data.digits)}`;
      const href=part.key==='budget'?'/budgets?'+new URLSearchParams({currency:data.currency,month:item.key?.length===7?item.key:data.month}):item.href;
      return `<g ${href?`role="link" tabindex="0" data-chart-href="${E(href)}"`:''} aria-label="${E(label)}"><title>${E(label)}</title><rect x="${x}" y="${topY}" width="${Math.max(1,barWidth-gap)}" height="${height}" rx="3" fill="${value<0n?'var(--negative)':part.colour}" class="overview-chart-bar"/></g>`;
    }).join('');
    const lastIndex=items.length-1;
    const labelled=index===lastIndex||(index%labelStep===0&&lastIndex-index>=labelStep);
    return grouped+(labelled?`<text class="overview-chart-x-label" x="${centre}" y="${H-19}" text-anchor="middle">${E(item.label)}</text>`:'');
  }).join('');
  return `<div class="overview-chart-legend">${series.map(part=>`<span><i style="background:${part.colour}"></i>${E(part.label)}</span>`).join('')}${lower<0n?'<span><i style="background:var(--negative)"></i>Net refund / deficit</span>':''}<span class="overview-chart-unit">${E(data.currency)}</span></div><div class="overview-svg-wrap"><svg class="overview-chart-svg" viewBox="0 0 ${W} ${H}" role="group" aria-label="${E(title)}"><title>${E(title)}</title><desc>${E(description)} Exact values and accessible record links are available in the chart data table.</desc>${axes}<line x1="${left}" x2="${W-right}" y1="${zero}" y2="${zero}" class="overview-chart-zero"/>${bars}</svg></div>`;
}

function signedCategories(data, categories, period, note) {
  const largest=categories.reduce((value,item)=>abs(item.value)>value?abs(item.value):value,1n);
  return `<p class="overview-chart-note">${E(note)}</p><div class="overview-signed-list">${categories.map(item=>`<div class="overview-signed-item"><div><span>${E(item.label)}</span><strong>${E(formatMinor(item.value,data.currency,data.digits))}</strong></div><div class="overview-signed-track"><span class="${item.value<0n?'negative-value':'positive-value'}" style="width:${Number(abs(item.value))/Number(largest)*48}%"></span></div></div>`).join('')}</div>`;
}

function doughnut(data, categories, label) {
  const total=sum(categories.map(item=>item.value)), radius=82,circumference=2*Math.PI*radius;
  const majorTotal=Number(total)/(10**data.digits);
  const centreTotal=majorTotal>=10000?'≈'+new Intl.NumberFormat('en-US',{notation:'compact',maximumFractionDigits:1}).format(majorTotal):formatMinor(total,'',data.digits).trim();
  let offset=0;
  const slices=categories.map((item,index)=>{
    if(item.value<=0n)return '';
    const fraction=Number(item.value)/Number(total),length=fraction*circumference;
    const result=`<circle cx="120" cy="120" r="${radius}" fill="none" stroke="${COLOURS[index%COLOURS.length]}" stroke-width="35" stroke-dasharray="${length} ${circumference-length}" stroke-dashoffset="${-offset}" transform="rotate(-90 120 120)"><title>${E(item.label)}: ${E(formatMinor(item.value,data.currency,data.digits))}</title></circle>`;
    offset+=length;return result;
  }).join('');
  return `<div class="overview-pie-layout"><svg viewBox="0 0 240 240" class="overview-pie" role="img" aria-label="${E(label)}"><title>${E(label)}</title><desc>${categories.map(item=>`${E(item.label)} ${E(formatMinor(item.value,data.currency,data.digits))}`).join('; ')}</desc>${slices}<text x="120" y="106" text-anchor="middle">${E(data.currency)}</text><text x="120" y="137" text-anchor="middle" class="overview-pie-label">${E(centreTotal)}</text></svg><ul class="overview-pie-legend">${categories.map((item,index)=>`<li><i style="background:${COLOURS[index%COLOURS.length]}"></i><span>${E(item.label)}</span><strong>${E(formatMinor(item.value,data.currency,data.digits))}</strong><small>${total?((Number(item.value)/Number(total))*100).toFixed(1):'0'}%</small></li>`).join('')}</ul></div>`;
}

function body(data, period, type) {
  const totals=period==='year'?data.yearTotals:data.monthTotals,scopeLabel=period==='year'?`Calendar year ${data.year}`:`${MONTHS[Number(data.month.slice(5))-1]} ${data.year}`;
  const money=value=>value===null?'Not set':formatMinor(value,data.currency,data.digits);
  let visual='',exact='',title='',note='';
  if(type==='expenses') {
    title=period==='year'?'Expenses by month':'Expenses by day';
    const items=(period==='year'?data.months:data.days).map(item=>({...item,href:recordsHref(data,{key:item.key})}));
    visual=totals.expenseCount?barChart(data,items,[{key:'expenses',label:'Net expenses',colour:'var(--chart)'}],title,'Negative bars show refunds exceeding expenses in that period.'):'<div class="overview-chart-empty"><h3>No expense records in this selection</h3><p>Add or import transactions, or choose another month or year. Missing records do not prove zero spending.</p></div>';
    exact=table([period==='year'?'Month':'Date','Net expenses','Expense records','Records'],items.map(item=>[E(item.key),E(money(item.expenses)),String(item.expenseCount??item.count),openLink(item.href)]),title+' · '+scopeLabel+' · '+data.currency);
    note=period==='year'?'All 12 calendar months are shown. Zero means no net amount was recorded; it does not establish that your history is complete.':'Every calendar day is shown. Refunds reduce net expenses. Transfers are excluded.';
  } else if(type==='budget') {
    title='Expenses vs budget';
    const items=period==='year'?data.months.map(item=>({...item,href:recordsHref(data,{key:item.key})})):[{label:MONTHS[Number(data.month.slice(5))-1],key:data.month,expenses:totals.expenses,budget:totals.budget,href:recordsHref(data)}];
    visual=totals.expenseCount||totals.budget!==null?barChart(data,items,[{key:'expenses',label:'Net expenses',colour:'var(--chart)'},{key:'budget',label:'Planned budget',colour:'var(--income)'}],title,'Months without a budget have no budget bar. A zero budget is an explicit limit.'):'<div class="overview-chart-empty"><h3>No expenses or budgets in this selection</h3><p>Add records or set a monthly budget to compare your plan with actual spending.</p></div>';
    exact=table(['Month','Net expenses','Planned budget','Budget remaining','Records'],items.map(item=>[E(item.key),E(money(item.expenses)),E(money(item.budget)),item.budget===null?'Not set':E(money(item.budget-item.expenses)),openLink(item.href)]),title+' · '+scopeLabel);
    note=totals.budget===null?'No budget is set for this selection. Missing limits are not treated as zero.':`${period==='year'?`${totals.budgetMonths} of 12 months have budgets. `:''}Category-wide limits include their subcategories; parent and child limits are not counted twice.`;
  } else if(type==='surplus') {
    title='Expenses & recorded surplus';
    const rows=[{label:'Net expenses',value:totals.expenses},{label:'Recorded surplus',value:totals.surplus}];
    if(!totals.count) visual='<div class="overview-chart-empty"><h3>No income or expense records in this year</h3><p>Add or import records to compare expenses with the recorded surplus.</p></div>';
    else if(totals.expenses<0n||totals.surplus<0n) visual=signedCategories(data,rows,period,totals.surplus<0n?`Expenses exceed recorded income by ${money(-totals.surplus)}. A signed comparison is shown because a pie cannot represent a deficit.`:`Refunds exceed expenses by ${money(-totals.expenses)}. Signed values are shown because a pie cannot represent negative expenses.`);
    else if(totals.income===0n) visual='<div class="overview-chart-empty"><h3>No positive total to divide</h3><p>Recorded income and net expenses are both zero. Exact values are shown below.</p></div>';
    else visual=doughnut(data,rows,title+' · '+scopeLabel);
    exact=table(['Measure','Amount'],[['Recorded income',E(money(totals.income))],...rows.map(item=>[E(item.label),E(money(item.value))])],title+' · '+scopeLabel);
    note='Recorded surplus = income − net expenses. It is not proof of money saved or invested; transfers are excluded.';
  } else {
    title='Expenses by category';const all=totals.categories;
    if(!totals.expenseCount) visual='<div class="overview-chart-empty"><h3>No expense categories in this selection</h3><p>Confirmed expense records are needed to show a category split.</p></div>';
    else if(all.some(item=>item.value<0n)) visual=signedCategories(data,all,period,'Some categories have net refunds. Signed bars preserve those negative amounts instead of showing a misleading pie.');
    else if(totals.expenses===0n) visual='<div class="overview-chart-empty"><h3>Net expenses are zero</h3><p>There is no positive amount for a category pie. Review the exact records and refunds below.</p></div>';
    else {const portions=all.length>8?[...all.slice(0,7),{label:`Other categories (${all.length-7})`,value:sum(all.slice(7).map(item=>item.value))}]:all;visual=doughnut(data,portions,title+' · '+scopeLabel);}
    exact=table(['Category','Net expenses','Records'],all.map(item=>[E(item.label),E(money(item.value)),openLink(recordsHref(data,{period,category:item.label}))]),title+' · '+scopeLabel);
    note='Category totals include all their subcategories. Refunds reduce spending. The table keeps every category separate.';
  }
  return `<div class="overview-chart-summary"><div><h3>${E(title)}</h3><p>${E(scopeLabel)} · ${E(data.currency)}</p></div><div><span>Net expenses</span><strong>${E(money(totals.expenses))}</strong></div></div>${visual}<p class="overview-chart-note">${E(note)}</p>${exact}`;
}

export function renderOverviewCharts(input) {
  const data=aggregateOverviewCharts(input),{period}=preference,type=choices(period).some(([key])=>key===preference.type)?preference.type:'expenses';
  return `<section class="card overview-charts" data-overview-charts>${controls(data,period,type)}<div data-chart-content aria-live="polite">${body(data,period,type)}</div></section>`;
}

export function bindOverviewCharts(root, input, onDrill) {
  const section=root.matches?.('[data-overview-charts]')?root:root.querySelector('[data-overview-charts]');
  if(!section)return;
  const data=aggregateOverviewCharts(input);
  function renderContent() {
    const content=section.querySelector('[data-chart-content]'),open=content.querySelector('details')?.open;
    data.chartWidth=Math.max(240,Math.min(1000,content.clientWidth));
    content.innerHTML=body(data,preference.period,preference.type);
    if(open)content.querySelector('details').open=true;
  }
  function update(focusType=false) {
    if(!choices(preference.period).some(([key])=>key===preference.type))preference.type='expenses';
    section.innerHTML=controls(data,preference.period,preference.type)+`<div data-chart-content aria-live="polite">${body(data,preference.period,preference.type)}</div>`;
    renderContent();
    if(focusType)section.querySelector('[data-chart-type]').focus();
    else section.querySelector(`[data-chart-period="${preference.period}"]`).focus();
  }
  section.addEventListener('change',event=>{if(event.target.matches('[data-chart-type]')){preference.type=event.target.value;update(true);}});
  section.addEventListener('click',event=>{
    const button=event.target.closest('[data-chart-period]');if(button){preference.period=button.dataset.chartPeriod;update();return;}
    const target=event.target.closest('[data-chart-href]');if(!target||event.ctrlKey||event.metaKey||event.shiftKey)return;
    if(onDrill){event.preventDefault();onDrill(target.dataset.chartHref);}
  });
  section.addEventListener('keydown',event=>{const target=event.target.closest('g[data-chart-href]');if(target&&['Enter',' '].includes(event.key)){event.preventDefault();if(onDrill)onDrill(target.dataset.chartHref);else location.assign(target.dataset.chartHref);}});
  renderContent();
  resizeObserver?.disconnect();
  if(window.ResizeObserver){resizeObserver=new ResizeObserver(()=>{if(!section.isConnected){resizeObserver?.disconnect();return;}const width=Math.max(240,Math.min(1000,section.querySelector('[data-chart-content]').clientWidth));if(Math.abs(width-data.chartWidth)>1)renderContent();});resizeObserver.observe(section);}
}
