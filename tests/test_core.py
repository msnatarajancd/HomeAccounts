import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import *

def transaction(**extra):
    return valid_tx({'date':'2026-10-10','type':'expense','amount':'45','currency':'USD','merchant':'Walmart','description':'Shopping','category':'Household','account':'Checking',**extra})

def budget(**extra):
    return valid_budget({'period':'2026-10','category':'Household','amount':'300','currency':'USD',**extra})

class FinanceTests(unittest.TestCase):
    def test_money_validation(self):
        self.assertEqual(cents('1,000.15'),100015)
        for v in ('nan','inf','1.001','abc','-5','1e100'):
            with self.assertRaises(ValueError): cents(v)
        with self.assertRaises(ValueError): transaction(date='2026-02-30')
        with self.assertRaises(ValueError): transaction(amount='0')
        with self.assertRaises(ValueError): transaction(currency='$')

    def test_budget_coaching(self):
        state={'transactions':[transaction(amount='270')],'budgets':[budget()]}
        result=impacts(state,transaction())[0]
        self.assertEqual(result['current'],'270.00')
        self.assertEqual(result['proposed_total'],'315.00')
        self.assertEqual(result['over_budget'],'15.00')
        self.assertEqual(state['budgets'][0]['amount'],'300.00')

    def test_refunds_currency_and_month_isolation(self):
        rows=[transaction(amount='100'),transaction(amount='-20'),transaction(amount='500',currency='INR'),transaction(amount='90',date='2026-09-30')]
        self.assertEqual(spending(rows,'2026-10','USD'),8000)
        self.assertEqual(income(rows,'2026-10','USD'),0)
        rows.append(transaction(type='transfer',amount='400'))
        self.assertEqual(spending(rows,'2026-10','USD'),8000)

    def test_edit_excludes_original_from_impact(self):
        old=transaction(amount='270')
        state={'transactions':[old],'budgets':[budget()]}
        self.assertEqual(impacts(state,transaction(amount='290'),old['id'])[0]['proposed_total'],'290.00')

    def test_subcategory_budget_not_double_counted(self):
        bs=[budget(),budget(subcategory='Cleaning',amount='50'),budget(category='Travel',subcategory='Flights',amount='90')]
        self.assertEqual(total_budget(bs,'2026-10','USD'),39000)

    def test_sentence_amount_date_and_ambiguity(self):
        history=[transaction(),transaction(category='American Grocery')]
        parsed,note=parse_sentence('I spent forty-five dollars at Walmart yesterday',dt.date(2026,10,11),'USD','Checking',history)
        self.assertEqual(parsed['amount'],'45.00'); self.assertEqual(parsed['date'],'2026-10-10')
        self.assertEqual(parsed['merchant'],'Walmart'); self.assertEqual(parsed['category'],'Uncategorized')
        self.assertIn('multiple categories',note)
        earned,_=parse_sentence('I earned 1000 yesterday',dt.date(2026,10,11),'USD','Checking',[])
        self.assertEqual(earned['type'],'income'); self.assertEqual(earned['merchant'],'')
        with self.assertRaises(ValueError): parse_sentence('I spent money on 2026-10-10',dt.date(2026,10,11),'USD','Checking',[])
        with self.assertRaises(ValueError): parse_sentence('I spent 1.001 yesterday',dt.date(2026,10,11),'USD','Checking',[])

    def test_coach_grounds_answers_and_stages_changes(self):
        row=transaction(amount='270')
        state={'transactions':[row],'budgets':[budget()]}
        response,proposal=coach('How much have I spent on Household?',state,'2026-10','USD','Checking',dt.date(2026,10,11))
        self.assertIn('270.00',response); self.assertIsNone(proposal)
        _,proposal=coach('delete transaction '+row['id'],state,'2026-10','USD','Checking',dt.date(2026,10,11))
        self.assertEqual(proposal['before'],[row]); self.assertEqual(len(state['transactions']),1)
        _,proposal=coach('set Household budget to 350 for 2026-10',state,'2026-10','USD','Checking',dt.date(2026,10,11))
        self.assertEqual(proposal['rows'][0]['amount'],'350.00')

    def test_total_income_is_not_expense_in_the_income_category(self):
        state={'transactions':[transaction(type='income',category='Income',amount='100'),
                               transaction(type='income',category='Salary',amount='50'),
                               transaction(type='income',category='Income',amount='999',currency='INR')],
               'budgets':[]}
        for question in ('What is my total income?', 'How much income did I receive?', 'Monthly income', 'Income'):
            with self.subTest(question=question):
                answer,proposal=coach(question,state,'2026-10','USD','Checking',dt.date(2026,10,11))
                self.assertIn('income 150.00',answer)
                self.assertIsNone(proposal)

    def test_multi_transaction_sentences_require_separate_entries(self):
        for text in ('I spent 45 and paid 20 yesterday', 'I spent 45 at a shop and 20 at a cafe',
                     'I earned 100 then I spent 20 today'):
            with self.subTest(text=text):
                with self.assertRaisesRegex(ValueError,'one transaction'):
                    parse_sentence(text,dt.date(2026,10,11),'USD','Checking',[])

    def test_csv_validation_and_dates(self):
        raw=b'date,type,amount,merchant,category\n2026-10-01,expense,20,Target,Household\n2026-02-30,expense,12,Target,Household\n'
        mapping={k:k for k in ['date','type','amount','merchant','category']}
        preview=normalize_import(read_tables(raw,'test.csv'),'test.csv',raw,mapping,['CSV'],'USD','Checking',2026,'ISO (YYYY-MM-DD)')
        self.assertEqual(len(preview['transactions']),1); self.assertEqual(len(preview['issues']),1)
        self.assertEqual(parse_date('46023.0',excel=True),'2026-01-01')
        self.assertEqual(parse_date('02/03/2026','US (MM/DD/YYYY)'),'2026-02-03')
        self.assertEqual(parse_date('02/03/2026','Day first (DD/MM/YYYY)'),'2026-03-02')

    def test_atomic_revisions_undo_stale_and_tombstones(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder); old=store.load()
            row=transaction(source_ref='file:Jan:2')
            first=store.commit([row],[budget()],old['revision'],'import')
            with self.assertRaises(ValueError): store.commit([],[],'','stale')
            second=store.commit([],store.load()['budgets'],first,'delete')
            preview={'transactions':[row],'budgets':[]}
            self.assertEqual(import_candidates(preview,store.load())[0],[])
            store.undo(second); self.assertEqual(store.load()['transactions'],[row])
            store.undo(first); self.assertEqual(store.load()['transactions'],[])

    def test_failed_pointer_write_keeps_both_old_csvs(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder)
            row=transaction(); first=store.commit([row],[budget()],'','first')
            def fail(info): raise OSError('Simulated pointer failure')
            store._pointer=fail
            with self.assertRaises(OSError): store.commit([],[],first,'failed')
            self.assertEqual(store.load()['transactions'],[row]); self.assertEqual(len(store.load()['budgets']),1)
            self.assertFalse((Path(folder)/'write.lock').exists())

    def test_budget_conflicts_and_possible_duplicates(self):
        a=transaction(); b=transaction()
        state={'transactions':[],'budgets':[budget()]}
        incoming,bs,duplicates,conflicts=import_candidates({'transactions':[a,b],'budgets':[budget(amount='400')]},state)
        self.assertEqual(len(incoming),2); self.assertEqual(len(duplicates),1); self.assertEqual(len(conflicts),1)

if __name__=='__main__': unittest.main()
