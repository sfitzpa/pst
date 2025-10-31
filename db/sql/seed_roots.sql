INSERT INTO root_truth (code,name,description) VALUES
 ('jc','Judeo-Christian','Reality created by a moral Lawgiver; coherence = obedience to moral order.'),
 ('is','Islamic','Reality is divine law; coherence = submission to God’s will.'),
 ('sh','Secular-Humanist','Reality is self-constructed; coherence = progress of human reason.'),
 ('ed','Eastern-Dharmic','Reality is cyclical illusion; coherence = detachment from material striving.')
ON CONFLICT (code) DO NOTHING;
