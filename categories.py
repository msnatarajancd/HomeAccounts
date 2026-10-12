"""Editable suggestions; not a formal or universal household standard."""
STARTER=[]
for typ,category,subs in [
    ('expense','Food',['Groceries','Dining out','Takeaway']),
    ('expense','Housing',['Rent','Utilities','Maintenance']),
    ('expense','Transport',['Public transport','Fuel','Vehicle maintenance']),
    ('expense','Household',['Supplies','Furniture']),
    ('expense','Health',['Medical','Medicines']),
    ('expense','Entertainment',['Subscriptions','Activities']),
    ('expense','Education',['Courses','Books']),
    ('expense','Personal',['Clothing','Care']),
    ('expense','Other',['Uncategorized']),
    ('income','Employment',['Salary','Bonus']),
    ('income','Other income',['Freelance','Interest','Gifts']),
    ('transfer','Transfers',['Between accounts','Savings','Investments'])]:
    for sub in subs: STARTER.append({'type':typ,'category':category,'subcategory':sub,'active':True})

def key(row): return tuple(str(row[k]).strip() for k in ('type','category','subcategory'))

def reconcile(rows,previous,transactions,budgets,known=()):
    out=[]; seen=set()
    for row in rows:
        typ=str(row.get('type','')).strip(); cat=str(row.get('category','')).strip(); sub=str(row.get('subcategory','') or '').strip()
        if typ not in ('income','expense','transfer') or not cat: raise ValueError('Each category needs a type and name.')
        r={'type':typ,'category':cat,'subcategory':sub,'active':bool(row.get('active',True))}
        if key(r) in seen: raise ValueError('Category/subcategory rows must be unique for each type.')
        seen.add(key(r)); out.append(r)
    refs={(t['type'],t['category'],t['subcategory']) for t in transactions}
    refs|={('expense',b['category'],b['subcategory']) for b in budgets}
    refs|={key(r) for r in known}
    for row in previous:
        k=key(row)
        referenced=k in refs or any(typ==k[0] and cat==k[1] and not sub for typ,cat,sub in refs)
        if k not in seen and referenced: out.append({**row,'active':False}); seen.add(k)
    return out

def options(taxonomy,transactions,typ):
    active=[r for r in taxonomy if r['type']==typ and r['active']]
    archived={r['category'] for r in taxonomy if r['type']==typ and not r['active']} - {r['category'] for r in active}
    existing={t['category'] for t in transactions if t['type']==typ and t['category'] not in archived}
    return sorted(existing|{r['category'] for r in active}|{'Uncategorized'})

def suboptions(taxonomy,transactions,typ,category):
    active={r['subcategory'] for r in taxonomy if r['type']==typ and r['category']==category and r['active']}
    archived={r['subcategory'] for r in taxonomy if r['type']==typ and r['category']==category and not r['active']}
    existing={t['subcategory'] for t in transactions if t['type']==typ and t['category']==category and t['subcategory'] not in archived}
    return ['']+sorted((active|existing)-{''})

def record_categories(transactions, budgets):
    """Exact references shared by expense records and expense budgets."""
    return [{'type':r['type'],'category':r['category'],'subcategory':r['subcategory']} for r in transactions]+[
        {'type':'expense','category':r['category'],'subcategory':r['subcategory']} for r in budgets]

def catalog(taxonomy, transactions, budgets, known=()):
    """Resolve choices without migrating or renaming existing user records.

    Explicit schema rows win over historical references, including archives.
    Parent-only rows support unspecified transaction detail/category-wide limits.
    """
    rows={}
    if not taxonomy:
        for typ,names in [('expense',('Household','Groceries','Dining','Transport')),
                          ('income',('Income',)),('transfer',('Transfers',))]:
            for name in names:
                row={'type':typ,'category':name,'subcategory':'','active':True,'source':'suggestion'}
                rows[key(row)]=row
    for row in [*known,*record_categories(transactions,budgets)]:
        item={k:str(row.get(k,'')).strip() for k in ('type','category','subcategory')}
        if item['type'] in ('income','expense','transfer') and item['category']:
            rows[key(item)]={**item,'active':True,'source':'confirmed'}
    for row in taxonomy:
        rows[key(row)]={**row,'source':'schema'}
    for typ in ('expense','income','transfer'):
        item={'type':typ,'category':'Uncategorized','subcategory':'','active':True,'source':'fallback'}
        rows.setdefault(key(item),item)
    parents={(r['type'],r['category']) for r in rows.values()}
    for typ,cat in parents:
        parent=(typ,cat,'')
        if parent not in rows:
            children=[r for r in rows.values() if r['type']==typ and r['category']==cat]
            rows[parent]={'type':typ,'category':cat,'subcategory':'',
                          'active':any(r['active'] for r in children),'source':'parent'}
        # Archiving every schema child also hides an implicit historical parent.
        definitions=[r for r in taxonomy if r['type']==typ and r['category']==cat]
        if definitions and not any(r['active'] for r in definitions) and rows[parent]['source']!='schema':
            rows[parent]={**rows[parent],'active':False}
    return sorted(rows.values(),key=lambda r:key(r))

def additions_for(rows, choices, before=(), *, importing=False):
    """Validate parent/type references; return new pairs requiring confirmation."""
    existing={key(row):row for row in choices}
    previous={(str(row.get('id','')),key(row)) for row in before}
    additions={}
    for row in rows:
        ref=key(row); prior=(str(row.get('id','')),ref) in previous
        match=existing.get(ref)
        if match:
            if not match['active'] and not prior and not importing:
                raise ValueError('This category/subcategory is archived. Choose an active pair or reactivate it in Categories.')
            continue
        if not importing:
            parent_choices=[r for r in choices if r['type']==row['type'] and r['category'].casefold()==row['category'].casefold()]
            if parent_choices and not any(r['active'] for r in parent_choices):
                raise ValueError('This category is archived. Reactivate it in Categories before adding a new subcategory.')
            if parent_choices and row['category'] not in {r['category'] for r in parent_choices}:
                raise ValueError(f'Use the existing category spelling: {parent_choices[0]["category"]}.')
            near=next((r for k,r in existing.items() if tuple(v.casefold() for v in k)==tuple(v.casefold() for v in ref)),None)
            if near:
                raise ValueError(f'Use the existing spelling: {near["category"]}' + (f' / {near["subcategory"]}.' if near['subcategory'] else '.'))
            parents={r['category'] for r in choices if r['type']==row['type'] and r['active'] and row['subcategory'] and r['subcategory'].casefold()==row['subcategory'].casefold()}
            if parents and row['category'] not in parents:
                raise ValueError(f'Subcategory {row["subcategory"]} belongs to {", ".join(sorted(parents))}. Choose its existing parent or define the new pair in Categories first.')
        additions[ref]={k:row[k] for k in ('type','category','subcategory')}
    return [additions[k] for k in sorted(additions)]
