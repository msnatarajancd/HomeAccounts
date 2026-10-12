import unittest
from planning import compound_growth,fire_target,variance

class PlanningTests(unittest.TestCase):
    def test_zero_rate_and_years(self):
        self.assertAlmostEqual(compound_growth(1000,100,5,0)[-1]['Projected value'],1500)
        self.assertEqual(compound_growth(1000,100,0,10)[-1]['Projected value'],1000)
    def test_timing(self):
        self.assertAlmostEqual(compound_growth(1000,100,1,10,timing='End')[-1]['Projected value'],1200)
        self.assertAlmostEqual(compound_growth(1000,100,1,10,timing='Beginning')[-1]['Projected value'],1210)
    def test_monthly_frequency_and_compounding(self):
        self.assertAlmostEqual(compound_growth(1000,100,1,0,frequency='Monthly')[-1]['Projected value'],2200)
        self.assertAlmostEqual(compound_growth(1000,0,1,12,12)[-1]['Projected value'],1000*1.01**12)
        end=compound_growth(0,100,1,12,12,'Monthly','End')[-1]['Projected value']
        begin=compound_growth(0,100,1,12,12,'Monthly','Beginning')[-1]['Projected value']
        self.assertAlmostEqual(end,100*((1.01**12-1)/.01)); self.assertAlmostEqual(begin,end*1.01)
    def test_inflation_and_negative_return(self):
        row=compound_growth(1000,0,1,-10,inflation=10)[-1]
        self.assertAlmostEqual(row['Projected value'],900); self.assertAlmostEqual(row['Inflation-adjusted value'],900/1.1)
    def test_invalid_inputs(self):
        for args in [(-1,0,1,5),(1000,0,-1,5),(1000,0,1,-100),(1000,0,1,float('nan')),(1000,0,1,5,0)]:
            with self.assertRaises(ValueError): compound_growth(*args)
        with self.assertRaises(ValueError): fire_target(50000,0)
    def test_fire_and_variance(self):
        self.assertEqual(fire_target(40000,4),1000000)
        self.assertEqual(variance(300,315),{'difference':15.,'percent':5.,'label':'Over budget'})
        self.assertEqual(variance(300,270)['percent'],-10.)
        self.assertIsNone(variance(0,10)['percent'])
        self.assertEqual(variance(0,0)['label'],'On budget')

if __name__=='__main__': unittest.main()
