WITH roots AS (
  SELECT code,id FROM root_truth
)
INSERT INTO frame (root_id,code,name,dimension,language,notes)
SELECT id,'proverbs_jc','Proverbs (Judeo-Christian)','ancient','en',
       'Hebrew wisdom literature aligned with covenantal moral order' FROM roots WHERE code='jc'
UNION ALL
SELECT id,'handey_sh','Jack Handey (Secular-Humanist humor)','modern','en',
       'American absurdist wit; irony as epistemic defense' FROM roots WHERE code='sh'
UNION ALL
SELECT id,'pauline_jc','Pauline Epistles (Judeo-Christian)','early','gr',
       'Early Christian theological corpus' FROM roots WHERE code='jc'
UNION ALL
SELECT id,'zen_ed','Zen Koans (Eastern-Dharmic)','classical','jp',
       'Paradox and detachment as means to enlightenment' FROM roots WHERE code='ed';
