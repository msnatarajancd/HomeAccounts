const {test, expect} = require('@playwright/test');
const fs=require('node:fs/promises');

const entry=(date,amount,type='expense',category='Food',currency='USD')=>({date,amount,type,category,currency,subcategory:''});
const limit=(period,amount,category='Food',subcategory='',currency='USD')=>({period,amount,category,subcategory,currency});
const fixture={currency:'USD',month:'2026-01',currencyDigits:2,transactions:[
  entry('2026-01-01','1000.00','income','Salary'),entry('2026-01-05','100.10'),entry('2026-01-06','50.20'),entry('2026-01-10','-20.00'),
  entry('2026-02-01','400.00','expense','Housing'),entry('2026-02-01','200.00','income','Salary'),
  entry('2026-01-05','9000.00','expense','Food','EUR'),entry('2026-01-05','999.00','transfer','Transfer'),entry('2025-12-31','500.00'),
],budgets:[limit('2026-01','200.00'),limit('2026-01','80.00','Food','Groceries'),limit('2026-01','90.00','Food','Dining'),limit('2026-02','500.00','Housing'),limit('2026-03','0.00'),limit('2026-01','9999.00','Food','','EUR')]};

test.beforeEach(async({page})=>{
  page.on('pageerror',error=>{throw error;});
  await page.route('**/*',route=>new URL(route.request().url()).hostname==='127.0.0.1'?route.continue():route.abort());
  await page.route('**/chart-test-harness',route=>route.fulfill({contentType:'text/html',body:`<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/assets/style.css"><link rel="stylesheet" href="/assets/overview-charts.css"><style>.fixture-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(0,1fr);gap:20px;align-items:start}@media(max-width:760px){.fixture-grid{grid-template-columns:1fr}}</style></head><body><main style="max-width:1120px;margin:30px auto;padding:16px"><div class="fixture-grid"><div id="mount"></div><aside id="neighbour" class="card">Adjacent budget panel</aside></div></main></body></html>`}));
});

async function mount(page,input=fixture){
  await page.goto('/chart-test-harness');
  await page.evaluate(async input=>{
    window.__charts=await import('/assets/overview-charts.js');window.__drills=[];
    window.__mount=input=>{const root=document.getElementById('mount');root.innerHTML=__charts.renderOverviewCharts(input);__charts.bindOverviewCharts(root,input,href=>__drills.push(href));};
    __mount(input);
  },input);
  await expect(page.getByRole('heading',{name:'Spending patterns'})).toBeVisible();
}

test('aggregates exact currency-scoped amounts, all months, refunds and parent budgets',async({page})=>{
  await mount(page);
  const result=await page.evaluate(input=>{
    const data=__charts.aggregateOverviewCharts(input);
    return JSON.parse(JSON.stringify(data,(_,value)=>typeof value==='bigint'?String(value):value));
  },fixture);
  expect(result.monthTotals).toMatchObject({income:'100000',expenses:'13030',surplus:'86970',budget:'20000',count:4,expenseCount:3});
  expect(result.yearTotals).toMatchObject({income:'120000',expenses:'53030',surplus:'66970',budget:'70000',budgetMonths:3});
  expect(result.months).toHaveLength(12);
  expect(result.months.map(item=>item.key)).toEqual(Array.from({length:12},(_,i)=>`2026-${String(i+1).padStart(2,'0')}`));
  expect(result.months[2].budget).toBe('0');
  expect(result.months[3].budget).toBeNull();
  expect(result.days).toHaveLength(31);
  expect(result.days[9].expenses).toBe('-2000');
  expect(result.monthTotals.categories).toEqual([{label:'Food',value:'13030'}]);
});

test('currency precision and large aggregate values remain exact without floating-point sums',async({page})=>{
  await mount(page);
  const actual=await page.evaluate(()=>{
    const base={budgets:[],currency:'KWD',month:'2024-02',currencyDigits:3};
    const data=__charts.aggregateOverviewCharts({...base,transactions:[{currency:'KWD',date:'2024-02-29',type:'expense',amount:'0.100',category:'Food'},{currency:'KWD',date:'2024-02-29',type:'expense',amount:'0.200',category:'Food'}]});
    const huge=__charts.aggregateOverviewCharts({...base,currency:'CLF',currencyDigits:4,transactions:Array.from({length:1001},()=>({currency:'CLF',date:'2024-02-01',type:'expense',amount:'1000000000.0000',category:'Housing'}))});
    return {days:data.days.length,total:String(data.monthTotals.expenses),display:__charts.formatMinor(data.monthTotals.expenses,'KWD',3),huge:String(huge.yearTotals.expenses),jpy:__charts.formatMinor(__charts.toMinor('1200',0),'JPY',0)};
  });
  expect(actual).toEqual({days:29,total:'300',display:'KWD 0.300',huge:'10010000000000000',jpy:'JPY 1,200'});
});

test('monthly and yearly controls expose exact budget data and scoped record links',async({page})=>{
  await mount(page);
  await page.getByText('View exact chart data',{exact:true}).click();
  const day=page.getByRole('row').filter({hasText:'2026-01-05'});
  await day.getByRole('link',{name:'Open records'}).click();
  let href=await page.evaluate(()=>__drills.at(-1));
  expect(new URL('http://local'+href).searchParams.get('column_date')).toBe('2026-01-05');
  await page.getByRole('button',{name:'Yearly',exact:true}).click();
  await expect(page.getByRole('button',{name:'Yearly',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByLabel('Overview chart type').selectOption('budget');
  await page.getByText('View exact chart data',{exact:true}).click();
  await expect(page.getByRole('table').locator('tbody tr')).toHaveCount(12);
  await expect(page.getByRole('row').filter({hasText:'2026-03'})).toContainText('USD 0.00');
  await expect(page.getByRole('row').filter({hasText:'2026-04'})).toContainText('Not set');
  await expect(page.locator('.overview-chart-note')).toContainText('3 of 12 months have budgets');
  await page.getByLabel('Overview chart type').selectOption('category');
  await page.getByText('View exact chart data',{exact:true}).click();
  await page.getByRole('row').filter({hasText:'Food'}).getByRole('link',{name:'Open records'}).click();
  href=await page.evaluate(()=>__drills.at(-1));
  const query=new URL('http://local'+href).searchParams;
  expect(Object.fromEntries(query)).toMatchObject({all:'1',column_date:'2026',category:'Food',currency:'USD',type:'expense'});
});

test('deficits and negative category refunds use signed values instead of misleading pies',async({page})=>{
  await mount(page,{...fixture,budgets:[],transactions:[entry('2026-01-01','100.00','income','Salary'),entry('2026-01-02','500.00','expense','Housing'),entry('2026-01-03','-20.00','expense','Food')]});
  await page.getByRole('button',{name:'Yearly',exact:true}).click();
  await page.getByLabel('Overview chart type').selectOption('surplus');
  await expect(page.locator('.overview-pie')).toHaveCount(0);
  await expect(page.locator('.overview-signed-list')).toContainText('USD −380.00');
  await expect(page.locator('[data-chart-content]')).toContainText('Expenses exceed recorded income by USD 380.00');
  await expect(page.locator('[data-chart-content]')).toContainText('not proof of money saved or invested');
  await page.getByLabel('Overview chart type').selectOption('category');
  await expect(page.locator('.overview-pie')).toHaveCount(0);
  await expect(page.locator('.overview-signed-list')).toContainText('USD −20.00');
  await expect(page.locator('[data-chart-content]')).toContainText('net refunds');
});

test('zero expenses keep the surplus slice colour consistent and missing history is explicit',async({page})=>{
  await mount(page,{...fixture,budgets:[],transactions:[entry('2026-01-01','100.00','income','Salary')]});
  await page.getByRole('button',{name:'Yearly',exact:true}).click();
  await page.getByLabel('Overview chart type').selectOption('surplus');
  await expect(page.locator('.overview-pie circle')).toHaveCount(1);
  expect(await page.locator('.overview-pie circle').getAttribute('stroke')).toBe('var(--income)');
  const legend=page.locator('.overview-pie-legend li').filter({hasText:'Recorded surplus'});
  expect(await legend.locator('i').getAttribute('style')).toContain('var(--income)');
  await expect(page.locator('.overview-pie-label')).toHaveText('100.00');
  await page.evaluate(()=>__mount({transactions:[],budgets:[],currency:'USD',month:'2026-01',currencyDigits:2}));
  await page.getByLabel('Overview chart type').selectOption('budget');
  await expect(page.locator('[data-chart-content]')).toContainText('No expenses or budgets in this selection');
  await expect(page.locator('[data-chart-content]')).toContainText('Missing limits are not treated as zero');
});

test('daily bars and twelve-month comparisons stay within cards on phones and desktop',async({page})=>{
  const crowded={...fixture,transactions:Array.from({length:365},(_,index)=>{
    const date=new Date(Date.UTC(2026,0,index+1)).toISOString().slice(0,10);
    return entry(date,String(20+index%19)+'.25','expense',index%2?'Food':'Transport');
  }),budgets:Array.from({length:12},(_,index)=>limit('2026-'+String(index+1).padStart(2,'0'),'900.00'))};
  for(const width of [375,834,1440]){
    await page.setViewportSize({width,height:1000});await mount(page,crowded);
    for(const view of ['month','year']){
      await page.getByRole('button',{name:view==='month'?'Monthly':'Yearly',exact:true}).click();
      if(view==='year')await page.getByLabel('Overview chart type').selectOption('budget');
      const bounds=await page.evaluate(()=>{
        const card=document.querySelector('[data-overview-charts]').getBoundingClientRect(),svg=document.querySelector('.overview-chart-svg').getBoundingClientRect();
        return {width:innerWidth,scroll:document.documentElement.scrollWidth,cardLeft:card.left,cardRight:card.right,svgLeft:svg.left,svgRight:svg.right,viewWidth:document.querySelector('.overview-chart-svg').viewBox.baseVal.width,rectWidth:svg.width};
      });
      expect(bounds.scroll).toBe(bounds.width);
      expect(bounds.svgLeft).toBeGreaterThanOrEqual(bounds.cardLeft);
      expect(bounds.svgRight).toBeLessThanOrEqual(bounds.cardRight);
      expect(Math.abs(bounds.viewWidth-bounds.rectWidth)).toBeLessThan(2);
      const labels=await page.locator('.overview-chart-x-label').evaluateAll(elements=>elements.map(element=>{
        const rect=element.getBoundingClientRect();return {label:element.textContent,left:rect.left,right:rect.right};
      }));
      for(let index=1;index<labels.length;index++)expect(labels[index].left,`${width}px ${view}: ${labels[index-1].label} and ${labels[index].label} overlap`).toBeGreaterThanOrEqual(labels[index-1].right);
      await page.getByText('View exact chart data',{exact:true}).click();
      const firstLink=page.getByRole('link',{name:'Open records',exact:true}).first();
      await expect(page.locator('.overview-chart-data')).toHaveAttribute('open','');
      await expect(firstLink).toBeVisible();
      // Opening the table may add a page scrollbar and trigger the chart resize observer.
      // Re-resolve the link after that render rather than measuring a detached element.
      await expect.poll(async()=>{const hit=await firstLink.boundingBox();return !!hit&&hit.width>=44&&hit.height>=44;}).toBe(true);
      await page.getByText('View exact chart data',{exact:true}).click();
    }
  }
});

test('nice axes label zero, zero days have no fake bars, and dense yearly charts are reviewable',async({page})=>{
  await mount(page,{...fixture,transactions:[entry('2026-01-01','146.00'),entry('2026-01-02','-16.00')],budgets:[]});
  const labels=await page.locator('.overview-chart-svg text[text-anchor="end"]').allTextContents();
  expect(labels).toEqual(['-50','0','50','100','150']);
  await expect(page.locator('.overview-chart-bar')).toHaveCount(2);
  const crowded={...fixture,transactions:Array.from({length:365},(_,index)=>entry(new Date(Date.UTC(2026,0,index+1)).toISOString().slice(0,10),String(15+(index*7)%180)+'.25','expense',['Housing','Groceries','Transport','Utilities','Health','Dining','Education','Entertainment','Clothing','Pets','Travel','Gifts'][index%12])),budgets:Array.from({length:12},(_,index)=>limit('2026-'+String(index+1).padStart(2,'0'),'3000.00'))};
  await fs.mkdir('test-results/chart-review',{recursive:true});
  for(const [name,width] of [['phone',375],['desktop',1440]]){
    await page.setViewportSize({width,height:1000});await mount(page,crowded);
    await page.getByRole('button',{name:'Yearly',exact:true}).click();
    await expect(page.locator('.overview-chart-bar')).toHaveCount(12);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({path:`test-results/chart-review/yearly-expenses-${name}.png`,fullPage:true});
    await page.getByLabel('Overview chart type').selectOption('category');
    await expect(page.locator('.overview-pie circle')).toHaveCount(8);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBe(width);
    await page.screenshot({path:`test-results/chart-review/yearly-category-${name}.png`,fullPage:true});
  }
});
