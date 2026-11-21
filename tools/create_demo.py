"""Validate an authored contract and optionally render a real Longform sample frame."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine.longform_contract import full_script, script_hash, validate_approved_script
from engine.longform_pipeline import stage_validate

CHAPTERS = [
    ('C01', 'Revisa el punto de partida', '''Antes de publicar un proyecto, revisa qué puede comprobar otra persona. Empieza por describir el problema con palabras sencillas y elige un ejemplo pequeño que represente el trabajo. Ese ejemplo debe mostrar una entrada clara, una transformación observable y una salida que se pueda revisar. Evita prometer resultados que todavía no has medido.

La documentación también forma parte del producto. Una persona nueva necesita saber qué instalar, qué ejecutar y qué debería encontrar al terminar. Si un paso depende de una cuenta, un servicio externo o una biblioteca adicional, dilo antes de empezar. Deja una alternativa de prueba cuando sea posible y explica exactamente qué demuestra. Mantén los datos personales fuera del ejemplo. Usa material propio y conserva las fuentes para que los cambios puedan verificarse después.'''),
    ('C02', 'Conserva pruebas del resultado', '''Después de preparar el ejemplo, comprueba sus instrucciones en una copia aislada. Así puedes distinguir lo que funciona por el proyecto de lo que funciona solamente por la configuración de tu equipo. Guarda los resultados de las comprobaciones y relaciónalos con la versión que realmente probaste. Una captura ayuda a entender el resultado; las pruebas muestran qué comportamiento revisaste.

Cuando encuentres un fallo, corrige su causa y repite las comprobaciones afectadas. Conserva el historial para poder explicar qué cambió y por qué. No reemplaces una medición desfavorable por una afirmación optimista. Explica sus límites y el siguiente trabajo necesario. Al cerrar la revisión, otra persona debería poder identificar el objetivo, reproducir el ejemplo y entender qué sigue pendiente. Esa claridad permite conversar sobre decisiones concretas y valorar el trabajo a partir de evidencia visible.'''),
]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render', action='store_true')
    parser.add_argument('--node', default=shutil.which('node'))
    parser.add_argument('--browser-executable')
    args = parser.parse_args()
    if os.environ.get('PROVIDER_MODE', 'mock').lower() == 'real':
        raise RuntimeError('Use PROVIDER_MODE=mock for this offline walkthrough')
    target = ROOT/'docs/examples'; target.mkdir(parents=True,exist_ok=True)
    data = {'schema_version':'1.0','run_id':'portfolio-example','script_locked':True,'script_hash':'','title':'Cómo revisar un proyecto antes de publicarlo','thumbnail_promise':'MUESTRA LO QUE PUEDES COMPROBAR','hook':'Antes de publicar un proyecto, revisa qué puede comprobar otra persona.','target_minutes':2,'language':'es','audience_profile':'Personas que revisan proyectos de software y necesitan ejemplos reproducibles con límites claros.','avatar_appearances':2,'chapters':[{'id':cid,'title':title,'spoken_text':text} for cid,title,text in CHAPTERS]}
    data['script_hash']=script_hash(full_script(data));data['run_id']='portfolio-'+data['script_hash'][:10]
    errors=validate_approved_script(data)
    if errors:raise RuntimeError('; '.join(errors))
    contract=target/'approved-script.example.json';contract.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    stage_validate(contract)
    props={'runId':data['run_id'],'durationMs':6000,'audioSrc':'','sfx':[],'musicBeds':[],'showCaptions':False,'showProgress':True,'brand':{'ink':'#ffffff','cream':'#101820','teal':'#8bd1c8','gold':'#ffffff','red':'#ffffff'},'theme':{'background':'#101820','surface':'#192632','text':'#ffffff','body':'#d9e4ec','muted':'#aab8c5','hairline':'#3b4b58','accent':'#8bd1c8','highlight':'#ffffff','danger':'#ffffff','fontDisplay':'Arial, sans-serif','fontBody':'Arial, sans-serif','typography':{'displayWeight':600,'bodyWeight':400},'effects':{'useShadows':False,'useGradients':False}},'shots':[{'shotId':'S0001','chapterId':'C01','startMs':0,'endMs':6000,'visualKind':'motion-card','source':'','mediaType':'card','sourceInMs':0,'sourceOutMs':0,'screenCopy':'KEEP THE SCRIPT LOCKED','subcopy':'Validate the contract before selecting media.','cardVariant':'chapter'}],'captions':[]}
    propfile=target/'render-props.json';propfile.write_text(json.dumps(props,indent=2)+'\n',encoding='utf-8')
    image=target/'render-frame.png'
    if args.render:
        if not args.node:raise RuntimeError('Install the documented Node.js runtime before rendering')
        cmd=[args.node,str(ROOT/'remotion/node_modules/@remotion/cli/remotion-cli.js'),'still','src/index.ts','Longform',str(image),'--props='+str(propfile),'--frame=45','--log=error']
        if args.browser_executable:cmd.append('--browser-executable='+args.browser_executable)
        subprocess.run(cmd,cwd=ROOT/'remotion',check=True,timeout=240)
    rendered=image.is_file()
    dimensions=None
    if rendered:
        header=image.read_bytes()[:24]
        if header[:8] != b'\x89PNG\r\n\x1a\n':raise RuntimeError('Invalid renderer output')
        dimensions=list(struct.unpack('>II',header[16:24]))
        if dimensions != [1920,1080]:raise RuntimeError('Unexpected composition dimensions')
    evidence={'mode':'offline_contract_and_renderer','contractValidated':True,'chapters':len(data['chapters']),'words':len(full_script(data).split()),'renderedFrame':rendered,'frameDimensions':dimensions,'composition':'Longform','previewOnly':True,'narrationGenerated':False,'liveProviderCalls':0,'productionQaClaimed':False}
    (target/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
    preview='<img src="render-frame.png" alt="Frame produced by the actual Longform composition">' if rendered else '<p>Run the documented --render command to produce the sample frame.</p>'
    report='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Longform rendering walkthrough</title><style>body{margin:0;background:#f5f7fa;color:#172033;font:17px/1.6 system-ui,sans-serif}main{max-width:1050px;margin:42px auto;padding:30px}h1{font-size:40px;line-height:1.15;letter-spacing:-1px}.panel{background:white;border:1px solid #dce2e9;border-radius:12px;padding:22px;margin:24px 0}.stats{display:flex;gap:48px;flex-wrap:wrap}b{display:block;font-size:28px}img{display:block;width:100%;height:auto;border-radius:8px}.muted{color:#526174}</style><main><p class="muted">Longform Video Engine · Actual contract and renderer output</p><h1>A validated input and a real composition frame</h1><p>An authored script fixture passed the application’s contract validator. The sample below is rendered by the existing Longform composition, using text and layout only.</p><section class="panel stats"><div><b>Validated</b>locked script contract</div><div><b>2 chapters</b>authored sample input</div><div><b>0</b>live provider calls</div></section><section class="panel">'''+preview+'''</section><p class="muted">This is a renderer-only sample frame. It does not include generated narration, external media, presenter footage, music, or production QA. The fixture’s lock flag exercises the input contract and does not assert human editorial approval of a production video.</p></main></html>'''
    (target/'walkthrough.html').write_text(report,encoding='utf-8')
    print(json.dumps(evidence))

if __name__ == '__main__':
    main()
