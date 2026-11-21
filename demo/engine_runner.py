from pathlib import Path
import json,re,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine.longform_contract import full_script,script_hash,validate_approved_script
data=json.load(sys.stdin);chapters=data['chapters']
text=full_script({'chapters':chapters});count=len(re.findall(r'\b[\w]+\b',text))
contract={'schema_version':'1.0','language':'en','run_id':'demo-'+data['id'],'script_locked':True,'script_hash':script_hash(text),'title':data['title'],'thumbnail_promise':data['title'],'hook':text.split('\n')[0].split('. ')[0],'target_minutes':count/data['wpm'],'audience_profile':'English-speaking builders reviewing the approved script.','chapters':chapters,'avatar_appearances':2}
errors=validate_approved_script(contract)
if errors:
    print(json.dumps({'error':{'code':'validation_failed','message':'The script contract was rejected. Use at least two uniquely numbered chapters, titles of three characters, and 80 characters of spoken text per chapter. Keep production notes out of narration.'}}))
else:print(json.dumps({'contract':contract,'valid':True,'narrationWords':count,'scope':'Validated script contract. Avatar slots and narration are planned; this does not certify a finished video.'}))
